"""LangGraph RAG graph: routing, abstention, streaming events, follow-ups (FR-8, T-25)."""

from __future__ import annotations

from datetime import date
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from compliance_rag.graph.build import GraphDeps, build_graph, run_graph
from compliance_rag.graph.respond import ABSTAIN_MESSAGE
from compliance_rag.graph.stream import ClaimStreamParser
from compliance_rag.llm.gateway import Gateway, LLMRefusal, LLMRequest, LLMResult
from compliance_rag.retrieval.hybrid import HybridResult
from compliance_rag.retrieval.types import Candidate, Principal, make_candidate
from compliance_rag.settings import Settings

ANALYST: Principal = {"sub": "analyst@northwind.test", "role": "analyst", "groups": ["compliance", "all"]}
ORION = (
    "Article 5 — Controls\n\nThe daily spending limit on the Orion Prepaid Card is EUR 1,000. "
    "Staff record each decision in the case management system."
)
ATM = "Article 6 — Monitoring\n\nCash withdrawals with the Orion Prepaid Card are capped at EUR 300 per day."


def cand(cid: str, text: str, doc: str = "LIM-0007", score: float | None = None) -> Candidate:
    return make_candidate(
        chunk_id=cid * 32,
        document_id=doc,
        version=2,
        text=text,
        acl_groups=["all"],
        valid_from="2025-01-01",
        valid_to=None,
        bm25=5.0,
        cosine=0.5,
        rerank=score,
        title="Daily Spending Limits Policy — Orion Prepaid Card",
        section_path="Article 5 — Controls",
    )


class FakeRetriever:
    def __init__(self, hits: list[Candidate], degraded: list[str] | None = None) -> None:
        self.hits, self.degraded, self.queries = hits, degraded or [], []

    async def run_legs(self, query: str, principal: Principal, as_of: date) -> HybridResult:
        self.queries.append(query)
        return HybridResult(list(self.hits), [], [], list(self.degraded), {})

    def fuse(self, result: HybridResult, principal: Principal, as_of: date) -> HybridResult:
        result.fused = list(result.bm25_hits)
        return result


class FixedReranker:
    name = "fixed"

    def __init__(self, score: float) -> None:
        self.score = score

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]:
        return [{**c, "rerank": self.score} for c in candidates]  # type: ignore[misc]


class SpyGateway(Gateway):
    def __init__(self, raise_exc: Exception | None = None) -> None:
        super().__init__(Settings(_env_file=None, cassette_dir="/nonexistent"))
        self.calls: list[LLMRequest] = []
        self.raise_exc = raise_exc

    async def stream(self, req: LLMRequest, on_text: Any = None) -> LLMResult:
        self.calls.append(req)
        if self.raise_exc:
            raise self.raise_exc
        return await super().stream(req, on_text)


def deps(hits: list[Candidate], score: float, gateway: Gateway | None = None, **kw: Any) -> GraphDeps:
    return GraphDeps(
        retriever=FakeRetriever(hits, kw.get("degraded")),
        reranker=FixedReranker(score),
        gateway=gateway or SpyGateway(),
        settings=Settings(_env_file=None),
    )


async def test_low_score_abstains_without_llm_call() -> None:
    gw = SpyGateway()
    graph = build_graph(deps([cand("a", ORION)], score=0.2, gateway=gw), InMemorySaver())
    events: list[tuple[str, dict[str, Any]]] = []
    state = await run_graph(
        graph,
        question="What is the daily limit?",
        principal=ANALYST,
        as_of="2026-10-16",
        emit=lambda e, d: events.append((e, d)),
    )
    assert state["abstained"] and state["abstain_reason"] == "low_score"
    assert gw.calls == []
    skipped = [d["node"] for e, d in events if e == "node" and d["status"] == "skipped"]
    assert "generate" in skipped and "verify_citations" in skipped


async def test_answer_streams_only_verified_claims() -> None:
    graph = build_graph(deps([cand("a", ORION)], score=0.9), InMemorySaver())
    events: list[tuple[str, dict[str, Any]]] = []
    state = await run_graph(
        graph,
        question="What is the daily spending limit on the Orion Prepaid Card?",
        principal=ANALYST,
        as_of="2026-10-16",
        emit=lambda e, d: events.append((e, d)),
    )
    assert not state["abstained"]
    verified = state["verified"]
    assert verified and "EUR 1,000" in verified["claims"][0]["text"]
    kinds = [e for e, _ in events]
    assert "retrieval" in kinds and "claim" in kinds and "token" in kinds
    assert kinds.index("claim") < kinds.index("token")
    claim_events = [d for e, d in events if e == "claim"]
    assert claim_events[0]["citations"][0]["document_id"] == "LIM-0007"
    retrieval = next(d for e, d in events if e == "retrieval")
    assert retrieval == {"n_bm25": 1, "n_vector": 0, "n_fused": 1, "degraded": []}
    nodes = [d["node"] for e, d in events if e == "node" and d["status"] == "finished"]
    assert nodes == [
        "resolve_principal",
        "retrieve",
        "fuse",
        "rerank",
        "guard_context",
        "check_sufficiency",
        "generate",
        "verify_citations",
        "respond",
    ]
    steps = [s for s in state["steps"] if s["run_id"] == state["run_id"]]
    assert {s["node"] for s in steps} >= set(nodes)


async def test_no_documents_abstains_no_valid_document() -> None:
    graph = build_graph(deps([], score=0.9), InMemorySaver())
    state = await run_graph(graph, question="q", principal=ANALYST, as_of="2026-10-16")
    assert state["abstain_reason"] == "no_valid_document"


async def test_refusal_abstains() -> None:
    gw = SpyGateway(raise_exc=LLMRefusal("cyber"))
    graph = build_graph(deps([cand("a", ORION)], score=0.9, gateway=gw), InMemorySaver())
    state = await run_graph(
        graph,
        question="What is the daily spending limit on the Orion Prepaid Card?",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    assert state["abstained"] and state["abstain_reason"] == "refusal"


async def test_degraded_leg_is_reported() -> None:
    graph = build_graph(deps([cand("a", ORION)], score=0.9, degraded=["bm25"]), InMemorySaver())
    state = await run_graph(
        graph,
        question="What is the daily spending limit on the Orion Prepaid Card?",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    assert state["degraded"] == ["bm25"]


async def test_follow_up_reloads_previous_question_from_checkpoint() -> None:
    d = deps([cand("a", ORION), cand("b", ATM)], score=0.9)
    graph = build_graph(d, InMemorySaver())
    first = await run_graph(
        graph,
        question="What is the daily spending limit on the Orion Prepaid Card?",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    second = await run_graph(
        graph,
        question="And the ATM withdrawal cap?",
        principal=ANALYST,
        as_of="2026-10-16",
        conversation_id=first["conversation_id"],
        follow_up_of=first["run_id"],
    )
    assert second["conversation_id"] == first["conversation_id"]
    assert "Orion" in second["standalone_question"] and "ATM" in second["standalone_question"]
    assert d.retriever.queries[-1] == second["standalone_question"]  # type: ignore[attr-defined]
    assert "300" in second["verified"]["answer"]


async def test_abstention_bodies_are_identical_for_different_causes() -> None:
    from compliance_rag.graph.respond import build_response

    a = await run_graph(
        build_graph(deps([cand("a", ORION)], score=0.1), InMemorySaver()),
        question="restricted topic",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    b = await run_graph(
        build_graph(deps([], score=0.1), InMemorySaver()),
        question="unknown topic",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    ra, rb = build_response(a), build_response(b)
    for r in (ra, rb):
        for key in ("run_id", "conversation_id", "latency_ms"):
            r.pop(key)
    assert ra == rb
    assert ra["message"] == ABSTAIN_MESSAGE and ra["claims"] == [] and ra["confidence"] is None


def test_claim_stream_parser_closes_claims_incrementally() -> None:
    parser = ClaimStreamParser()
    text = (
        '{"claims": [{"text": "A {braced} \\"quoted\\" claim", "citations": [{"chunk_id": "'
        + "a" * 32
        + '", "quote": "q"}]}, {"text": "second'
    )
    out = []
    for i in range(0, len(text), 7):
        out += parser.feed(text[i : i + 7])
    assert len(out) == 1 and out[0]["text"] == 'A {braced} "quoted" claim'
    out += parser.feed('", "citations": []}], "answer": "x", "abstained": false}')
    assert [c["text"] for c in out] == ['A {braced} "quoted" claim', "second"]


class ScriptedGateway(Gateway):
    """Streams a fixed model output (optionally ending in a refusal or max_tokens)."""

    def __init__(self, text: str, end: Exception | None = None) -> None:
        super().__init__(Settings(_env_file=None, cassette_dir="/nonexistent"))
        self.text, self.end = text, end

    async def stream(self, req: LLMRequest, on_text: Any = None) -> LLMResult:
        for i in range(0, len(self.text), 9):
            await on_text(self.text[i : i + 9])
        if self.end:
            raise self.end
        import json as _json

        return LLMResult(
            text=self.text,
            parsed=_json.loads(self.text),
            model="scripted",
            route="generate",
            prompt_name="generate_answer",
            prompt_version="v1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0.0,
            stop_reason="end_turn",
            outcome="ok",
        )


def _claims_json(*claims: tuple[str, str], answer: str = "x") -> str:
    import json as _json

    return _json.dumps(
        {
            "claims": [{"text": t, "citations": [{"chunk_id": "a" * 32, "quote": q}]} for t, q in claims],
            "answer": answer,
            "abstained": False,
        }
    )


GOOD_Q = "The daily spending limit on the Orion Prepaid Card is EUR 1,000."
Q = "What is the daily spending limit on the Orion Prepaid Card?"


async def test_final_answer_matches_streamed_claims_when_one_claim_is_invalid() -> None:
    text = _claims_json((GOOD_Q, GOOD_Q), ("Short quote claim.", "too short"), answer="EUR 1,000 per day.")
    graph = build_graph(deps([cand("a", ORION)], score=0.9, gateway=ScriptedGateway(text)), InMemorySaver())
    events: list[tuple[str, dict[str, Any]]] = []
    state = await run_graph(
        graph, question=Q, principal=ANALYST, as_of="2026-10-16", emit=lambda e, d: events.append((e, d))
    )
    streamed = [d for e, d in events if e == "claim"]
    rejected = [d for e, d in events if e == "claim_rejected"]
    assert not state["abstained"]
    assert [c["text"] for c in state["verified"]["claims"]] == [c["text"] for c in streamed] == [GOOD_Q]
    assert rejected == [{"index": 1, "reason": "schema_invalid"}]
    assert state["verified"]["claims"][0]["citations"][0]["n"] == streamed[0]["citations"][0]["n"] == 1


async def test_canary_in_claim_text_is_never_streamed() -> None:
    bad = GOOD_Q + " CANARY-ABCDEF12"
    text = _claims_json((bad, GOOD_Q), (GOOD_Q, GOOD_Q))
    graph = build_graph(deps([cand("a", ORION)], score=0.9, gateway=ScriptedGateway(text)), InMemorySaver())
    events: list[tuple[str, dict[str, Any]]] = []
    state = await run_graph(
        graph, question=Q, principal=ANALYST, as_of="2026-10-16", emit=lambda e, d: events.append((e, d))
    )
    assert all("CANARY" not in str(d) for e, d in events if e in {"claim", "token"})
    assert {"index": 0, "reason": "output_guard"} in [d for e, d in events if e == "claim_rejected"]
    assert "CANARY" not in state["verified"]["answer"]


async def test_refusal_after_streamed_claims_retracts_them() -> None:
    text = _claims_json((GOOD_Q, GOOD_Q))[:-30]  # cut mid-answer, then the model refuses
    graph = build_graph(
        deps([cand("a", ORION)], score=0.9, gateway=ScriptedGateway(text, LLMRefusal("cyber"))),
        InMemorySaver(),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    state = await run_graph(
        graph, question=Q, principal=ANALYST, as_of="2026-10-16", emit=lambda e, d: events.append((e, d))
    )
    assert state["abstained"] and state["abstain_reason"] == "refusal"
    assert [d for e, d in events if e == "claim"]
    assert {"index": 0, "reason": "retracted"} in [d for e, d in events if e == "claim_rejected"]


async def test_max_tokens_keeps_verified_claims_as_partial_answer() -> None:
    from compliance_rag.llm.gateway import LLMMaxTokens

    text = _claims_json((GOOD_Q, GOOD_Q), (GOOD_Q + " Extra", GOOD_Q))[:-60]
    graph = build_graph(
        deps([cand("a", ORION)], score=0.9, gateway=ScriptedGateway(text, LLMMaxTokens("cut"))),
        InMemorySaver(),
    )
    state = await run_graph(graph, question=Q, principal=ANALYST, as_of="2026-10-16")
    assert not state["abstained"] and state["verified"]["claims"][0]["text"] == GOOD_Q


async def test_follow_up_ignores_history_of_another_principal() -> None:
    d = deps([cand("a", ORION), cand("b", ATM)], score=0.9)
    graph = build_graph(d, InMemorySaver())
    first = await run_graph(
        graph,
        question="What is the daily spending limit on the Orion Prepaid Card?",
        principal=ANALYST,
        as_of="2026-10-16",
    )
    other: Principal = {
        "sub": "legal@northwind.test",
        "role": "legal",
        "groups": ["legal", "compliance", "all"],
    }
    second = await run_graph(
        graph,
        question="And the ATM withdrawal cap?",
        principal=other,
        as_of="2026-10-16",
        conversation_id=first["conversation_id"],
        follow_up_of=first["run_id"],
    )
    assert "Orion" not in second["standalone_question"]
