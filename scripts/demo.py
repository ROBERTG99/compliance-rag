"""Scripted demo of the §3.4 user journeys against a running stack, offline (FakeLLM, dev-oidc personas).

    uv run python scripts/demo.py --api http://localhost:8610 --oidc http://localhost:8612

Exits non-zero if any step does not behave as the spec describes. ``run_demo`` is also driven in-process by
``tests/integration/test_demo.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

AS_OF = "2026-10-16"
POA_QUESTION = "What is the maximum age of a proof-of-address document?"
LEGAL_ONLY_QUESTION = (
    "How long are complaint files under a litigation hold preserved after the hold is lifted?"
)
AML_V4_META = {
    "document_id": "AML-0107",
    "version": "4",
    "title": "Correspondent Banking Due Diligence",
    "domain": "aml",
    "owner": "MLRO",
    "valid_from": "2026-09-01",
    "acl_groups": "compliance",
}

ClientFor = Callable[[str], AbstractAsyncContextManager[httpx.AsyncClient]]
ProcessJob = Callable[[str], Awaitable[None]]


class DemoFailed(RuntimeError):
    pass


@dataclass
class Step:
    name: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if "event" in fields:
            events.append(
                {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
            )
    return events


def aml0107_v4() -> bytes:
    """The next AML-0107 version: v3's text with the review cycle shortened from 18 to 12 months."""
    from data.generator.corpus import build_corpus
    from data.generator.render import render_version

    policy = next(p for p in build_corpus(2026) if p.document_id == "AML-0107")
    v3 = policy.versions[2]
    v3.version = 4
    return render_version(policy, v3, "md").replace(b"every 18 months", b"every 12 months")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise DemoFailed(message)


def highlight(text: str, quote: str, context: int = 60) -> str:
    """The quote marked with [[ ]] plus a little context on each side (single line)."""
    at = text.find(quote)
    if at < 0:
        return text[: 2 * context]
    start, end = max(0, at - context), min(len(text), at + len(quote) + context)
    snippet = f"{text[start:at]}[[{quote}]]{text[at + len(quote) : end]}"
    return ("…" if start else "") + " ".join(snippet.split()) + ("…" if end < len(text) else "")


async def _json(resp: httpx.Response, *expected: int) -> Any:
    _expect(
        resp.status_code in expected,
        f"{resp.request.method} {resp.request.url.path} → {resp.status_code}: {resp.text[:300]}",
    )
    return resp.json()


async def main_journey(client_for: ClientFor, log: Callable[[str], None]) -> list[Step]:
    steps: list[Step] = []
    async with client_for("analyst") as analyst:
        me = await _json(await analyst.get("/v1/me"), 200)
        _expect(me["role"] == "analyst", f"signed in as {me['role']}")
        steps.append(Step("1 sign in", f"{me['sub']} ({me['role']}, groups {', '.join(me['groups'])})"))

        accepted = await _json(
            await analyst.post("/v1/ask", json={"question": POA_QUESTION, "as_of": AS_OF, "stream": True}),
            202,
        )
        steps.append(Step("2 ask", f"{POA_QUESTION!r} → run {accepted['run_id']}"))
        events = parse_sse((await analyst.get(accepted["events_url"], timeout=60)).text)
        _expect(bool(events) and events[-1]["event"] == "final", "the event stream did not end with `final`")
        nodes = [
            e["data"]["node"] for e in events if e["event"] == "node" and e["data"]["status"] == "finished"
        ]
        steps.append(Step("3 progress", " → ".join(n for n in nodes if n) or "(no node events)"))
        claims = [e["data"] for e in events if e["event"] == "claim"]
        _expect(bool(claims), "no verified claim was streamed")
        for claim in claims:
            refs = "".join(f"[{c['n']}]" for c in claim["citations"])
            log(f"    claim {claim['index']}: {claim['text']} {refs}")
        steps.append(Step("4 claims", f"{len(claims)} verified claim(s) streamed with numbered citations"))

        final = events[-1]["data"]
        versions = [(v["document_id"], v["version"]) for v in final["versions"]]
        _expect(
            final["as_of"] == AS_OF and ("KYC-0042", 3) in versions,
            f"final as_of/versions: {final['as_of']} {versions}",
        )
        _expect(final["label"] == "AI-generated", "the answer is not labelled AI-generated")
        steps.append(
            Step("5 final", f"as of {final['as_of']}, cites " + ", ".join(f"{d} v{v}" for d, v in versions))
        )

        first = claims[0]["citations"][0]
        chunk = await _json(await analyst.get(f"/v1/chunks/{first['chunk_id']}"), 200)
        _expect(first["quote"] in chunk["text"], "the cited quote is not in the evidence chunk")
        steps.append(
            Step(
                "6 evidence",
                f"{chunk['document_id']} v{chunk['version']} § {chunk['section_path']}: "
                + highlight(chunk["text"], first["quote"]),
            )
        )

        fb = await analyst.post(
            "/v1/feedback", json={"run_id": final["run_id"], "rating": "up", "reason": "correct"}
        )
        await _json(fb, 200, 201)
        steps.append(Step("7 thumbs up", f"feedback {'recorded' if fb.status_code == 201 else 'updated'}"))
    return steps


async def _wait_for_job(
    admin: httpx.AsyncClient, job_id: str, process_job: ProcessJob | None, timeout_s: float
) -> str:
    if process_job is not None:
        await process_job(job_id)
    deadline = time.monotonic() + timeout_s
    while True:
        jobs = await _json(
            await admin.get("/v1/ingestion-jobs", params={"kind": "ingest", "limit": 500}), 200
        )
        status = next((j["status"] for j in jobs["items"] if j["job_id"] == job_id), "missing")
        if status in {"done", "failed"} or time.monotonic() > deadline:
            return status
        await asyncio.sleep(1.0)


async def secondary_journeys(
    client_for: ClientFor, process_job: ProcessJob | None = None, job_timeout_s: float = 300
) -> list[Step]:
    steps: list[Step] = []
    async with client_for("admin") as admin:
        upload = await admin.post(
            "/v1/documents",
            data=AML_V4_META,
            files={"file": ("aml-0107-v4.md", aml0107_v4(), "text/markdown")},
        )
        job = await _json(upload, 202)
        status = await _wait_for_job(admin, job["job_id"], process_job, job_timeout_s)
        _expect(status == "done", f"ingestion job {job['job_id']} ended {status}")
        doc = await _json(await admin.get("/v1/documents/AML-0107"), 200)
        by_version = {v["version"]: v for v in doc["versions"]}
        _expect(
            by_version[4]["in_force"] and by_version[3]["valid_to"] == "2026-09-01",
            "v3 was not superseded by v4",
        )
        steps.append(
            Step(
                "a upload",
                f"AML-0107 v4 job {status}; v3 valid until {by_version[3]['valid_to']}, v4 in force",
            )
        )

    async with client_for("support") as support:
        body = await _json(
            await support.post(
                "/v1/ask", json={"question": LEGAL_ONLY_QUESTION, "as_of": AS_OF, "stream": False}
            ),
            200,
        )
        _expect(body["abstained"] and "CMP-0215" not in json.dumps(body), "support saw the Legal-only policy")
        steps.append(Step("b legal-only", f"support gets the uniform abstention: {body['message']!r}"))

    async with client_for("analyst") as analyst:
        body = await _json(
            await analyst.post(
                "/v1/ask", json={"question": POA_QUESTION, "as_of": "2025-12-31", "stream": False}
            ),
            200,
        )
        cited = body["versions"][0] if body["versions"] else {}
        _expect(
            cited.get("document_id") == "KYC-0042"
            and cited.get("version") == 2
            and cited.get("superseded") is True,
            f"as_of 2025-12-31 cited {cited}",
        )
        steps.append(Step("c as_of", f"as of 2025-12-31: KYC-0042 v2 (superseded) — {body['answer'][:120]}"))
    return steps


async def run_demo(
    client_for: ClientFor, *, log: Callable[[str], None] = print, process_job: ProcessJob | None = None
) -> list[Step]:
    log("Main journey (§3.4)")
    steps = await main_journey(client_for, log)
    for s in steps:
        log(f"  {s.name}: {s.detail}")
    log("Secondary journeys")
    more = await secondary_journeys(client_for, process_job)
    for s in more:
        log(f"  {s.name}: {s.detail}")
    return steps + more


def http_clients(api: str, oidc: str) -> ClientFor:
    @asynccontextmanager
    async def client_for(persona: str) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(base_url=oidc, timeout=10) as idp:
            token = (await _json(await idp.post("/dev/token", json={"persona": persona}), 200))[
                "access_token"
            ]
        async with httpx.AsyncClient(
            base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=60
        ) as c:
            yield c

    return client_for


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8610")
    parser.add_argument("--oidc", default="http://localhost:8612")
    args = parser.parse_args(argv)
    try:
        asyncio.run(run_demo(http_clients(args.api, args.oidc)))
    except (DemoFailed, httpx.HTTPError) as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1
    print("demo ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
