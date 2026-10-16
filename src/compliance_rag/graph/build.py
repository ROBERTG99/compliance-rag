"""LangGraph RAG graph (BUILD.md §4.6).

resolve_principal → condense_followup (only with follow_up_of) → retrieve → fuse → rerank →
guard_context → check_sufficiency → generate → verify_citations → respond, with check_sufficiency,
generate and verify_citations routing to abstain. No interrupts: the graph has no side effects.
The checkpointer is keyed by ``thread_id = conversation_id`` so a follow-up sees the previous turn.

Events (SSE §4.5) are emitted through a context variable, never through checkpointed config.
"""

from __future__ import annotations

import asyncio
import operator
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Protocol

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from compliance_rag.graph.respond import build_response
from compliance_rag.graph.state import Claim, RagState, VerifiedAnswer, VerifiedClaim
from compliance_rag.graph.stream import ClaimStreamParser
from compliance_rag.graph.verify import final_answer, locate, verify_claim
from compliance_rag.guard.context_guard import guard_text
from compliance_rag.guard.output_guard import check_output
from compliance_rag.llm.gateway import Gateway, LLMError, LLMMaxTokens, LLMRefusal, LLMRequest, LLMResult
from compliance_rag.llm.prompts import load_prompt
from compliance_rag.obs.metrics import ABSTENTIONS, CLAIMS_REJECTED, CLAIMS_VERIFIED, TTFT_SECONDS
from compliance_rag.obs.steps import StepRecord, make_step
from compliance_rag.retrieval.hybrid import HybridResult
from compliance_rag.retrieval.types import Candidate, Principal
from compliance_rag.settings import Settings

Emit = Callable[[str, dict[str, Any]], Any]
EMIT: ContextVar[Emit | None] = ContextVar("crag_emit", default=None)
RUN_STARTED: ContextVar[float] = ContextVar("crag_run_started", default=0.0)
GENERATE_PROMPT = ("generate_answer", "v1")
CONDENSE_PROMPT = ("condense_followup", "v1")
VALID_GROUPS = {"all", "compliance", "legal", "support"}
MAX_CLAIMS = 8


class Retriever(Protocol):
    async def run_legs(self, query: str, principal: Principal, as_of: date) -> HybridResult: ...
    def fuse(self, result: HybridResult, principal: Principal, as_of: date) -> HybridResult: ...


class RerankerLike(Protocol):
    name: str

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]: ...


@dataclass
class GraphDeps:
    retriever: Retriever
    reranker: RerankerLike
    gateway: Gateway
    settings: Settings


class GraphState(RagState, total=False):
    history: Annotated[list[dict[str, Any]], operator.add]
    leg_result: dict[str, Any]


GENERATED_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["chunk_id", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "citations"],
                "additionalProperties": False,
            },
        },
        "answer": {"type": "string"},
        "abstained": {"type": "boolean"},
    },
    "required": ["claims", "answer", "abstained"],
    "additionalProperties": False,
}


async def emit(event: str, data: dict[str, Any]) -> None:
    fn = EMIT.get()
    if fn is None:
        return
    result = fn(event, data)
    if hasattr(result, "__await__"):
        await result


def _node(
    name: str,
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Wrap a node: node started/finished events and one StepRecord per execution."""

    def deco(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def wrapper(state: GraphState) -> dict[str, Any]:
            await emit("node", {"node": name, "status": "started", "latency_ms": 0})
            started = time.perf_counter()
            try:
                update = await fn(state)
            except Exception as exc:
                latency = (time.perf_counter() - started) * 1000
                await emit("node", {"node": name, "status": "error", "latency_ms": round(latency, 1)})
                raise exc
            latency = (time.perf_counter() - started) * 1000
            extra_steps: list[StepRecord] = update.pop("_steps", [])
            step = make_step(state["run_id"], name, latency_ms=latency)
            update["steps"] = [step, *extra_steps]
            await emit("node", {"node": name, "status": "finished", "latency_ms": round(latency, 1)})
            return update

        wrapper.__name__ = name
        return wrapper

    return deco


async def _skip(run_id: str, *nodes: str) -> list[StepRecord]:
    steps = []
    for n in nodes:
        await emit("node", {"node": n, "status": "skipped", "latency_ms": 0})
        steps.append(make_step(run_id, n, status="skipped"))
    return steps


def _documents_block(context: list[Candidate]) -> str:
    parts = []
    for c in context:
        body = c["text"].replace("</document>", "&lt;/document&gt;")
        parts.append(
            f'<document chunk_id="{c["chunk_id"]}" version="{c["version"]}" document_id="{c["document_id"]}" '
            f'title="{c.get("title", "")}">\n{body}\n</document>'
        )
    return "\n\n".join(parts)


def build_graph(deps: GraphDeps, checkpointer: Any | None = None) -> Any:
    settings = deps.settings

    @_node("resolve_principal")
    async def resolve_principal(state: GraphState) -> dict[str, Any]:
        principal = state["principal"]
        groups = [g for g in principal.get("groups", []) if g in VALID_GROUPS]
        if not groups:
            raise PermissionError("principal has no recognised groups")
        update: dict[str, Any] = {
            "principal": {**principal, "groups": groups},
            "standalone_question": state["question"],
            "bm25_hits": [],
            "vector_hits": [],
            "fused": [],
            "reranked": [],
            "context": [],
            "removed_sentences": 0,
            "draft": None,
            "verified": None,
            "abstained": False,
            "abstain_reason": None,
            "degraded": [],
            "confidence": 0.0,
            "cost_usd": 0.0,
        }
        if not state.get("follow_up_of"):
            update["_steps"] = await _skip(state["run_id"], "condense_followup")
        return update

    @_node("condense_followup")
    async def condense_followup(state: GraphState) -> dict[str, Any]:
        # only the caller's own turns may feed the rewrite (the API also enforces conversation ownership)
        history = [h for h in state.get("history") or [] if h.get("sub") == state["principal"]["sub"]]
        previous = next((h for h in reversed(history) if h["run_id"] == state.get("follow_up_of")), None)
        if previous is None and history:
            previous = history[-1]
        if previous is None:
            return {"standalone_question": state["question"], "previous": None}
        name, version = CONDENSE_PROMPT
        req = LLMRequest(
            route="condense_followup",
            system=load_prompt(name, version),
            user=f"Previous question: {previous['question']}\nCited documents: {'; '.join(previous.get('titles', []))}\n"
            f"Follow-up: {state['question']}",
            schema={
                "type": "object",
                "properties": {"standalone_question": {"type": "string"}},
                "required": ["standalone_question"],
                "additionalProperties": False,
            },
            schema_name="condensed_question",
            prompt_name=name,
            prompt_version=version,
            data={"question": state["question"], "previous_question": previous["question"]},
        )
        try:
            result = await deps.gateway.complete(req)
            standalone = str((result.parsed or {}).get("standalone_question") or "").strip()
            step = make_step(
                state["run_id"],
                "llm:condense_followup",
                kind="llm",
                model=result.model,
                prompt_version=version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
            )
            cost = result.cost_usd
        except LLMError:
            standalone, step, cost = (
                "",
                make_step(state["run_id"], "llm:condense_followup", kind="llm", status="error"),
                0.0,
            )
        if not standalone:
            standalone = f"{state['question']} ({previous['question']})"
        return {
            "standalone_question": standalone,
            "previous": previous,
            "_steps": [step],
            "cost_usd": state.get("cost_usd", 0.0) + cost,
        }

    @_node("retrieve")
    async def retrieve(state: GraphState) -> dict[str, Any]:
        result = await deps.retriever.run_legs(
            state["standalone_question"], state["principal"], date.fromisoformat(state["as_of"])
        )
        return {
            "bm25_hits": result.bm25_hits,
            "vector_hits": result.vector_hits,
            "degraded": result.degraded,
            "leg_result": {"timings": result.timings_ms},
        }

    @_node("fuse")
    async def fuse(state: GraphState) -> dict[str, Any]:
        result = HybridResult(
            list(state["bm25_hits"]), list(state["vector_hits"]), [], list(state["degraded"]), {}
        )
        result = deps.retriever.fuse(result, state["principal"], date.fromisoformat(state["as_of"]))
        await emit(
            "retrieval",
            {
                "n_bm25": result.n_bm25,
                "n_vector": result.n_vector,
                "n_fused": result.n_fused,
                "degraded": result.degraded,
            },
        )
        return {"fused": result.fused}

    @_node("rerank")
    async def rerank(state: GraphState) -> dict[str, Any]:
        top = state["fused"][: settings.leg_k]
        # Cohere on Bedrock and provider embeddings (cosine fill) block: run them in a worker thread
        reranked = await asyncio.to_thread(
            deps.reranker.rerank, state["standalone_question"], list(top), date.fromisoformat(state["as_of"])
        )
        return {"reranked": reranked}

    @_node("guard_context")
    async def guard_context(state: GraphState) -> dict[str, Any]:
        context: list[Candidate] = []
        removed = 0
        for c in state["reranked"][: settings.topk_context]:
            guarded = guard_text(c["text"])
            removed += guarded.removed
            context.append({**c, "text": guarded.text})
        return {"context": context, "removed_sentences": removed}

    @_node("check_sufficiency")
    async def check_sufficiency(state: GraphState) -> dict[str, Any]:
        context = state["context"]
        reason: str | None
        if not context:
            reason = "no_valid_document"
        else:
            top = float(context[0].get("rerank") or 0.0)
            reason = "low_score" if top < settings.abstain_tau else None
        if reason:
            return {
                "abstained": True,
                "abstain_reason": reason,
                "confidence": 0.0,
                "_steps": await _skip(state["run_id"], "generate", "verify_citations"),
            }
        return {"confidence": float(context[0].get("rerank") or 0.0)}

    @_node("generate")
    async def generate(state: GraphState) -> dict[str, Any]:
        """Stream the model output; every closed claim is schema-checked, output-guarded and verified
        before it is emitted. The final answer is assembled from exactly the claims that streamed."""
        name, version = GENERATE_PROMPT
        context = state["context"]
        by_id = {c["chunk_id"]: c for c in context}
        context_texts = [c["text"] for c in context]
        req = LLMRequest(
            route="generate",
            system=load_prompt(name, version),
            user=f"As of: {state['as_of']}\nQuestion: {state['standalone_question']}\n\n{_documents_block(context)}",
            schema=GENERATED_ANSWER_SCHEMA,
            schema_name="generated_answer",
            prompt_name=name,
            prompt_version=version,
            data={
                "question": state["standalone_question"],
                "context": [{"chunk_id": c["chunk_id"], "text": c["text"]} for c in context],
            },
        )
        parser = ClaimStreamParser()
        numbering: dict[str, int] = {}
        verified: list[VerifiedClaim] = []
        rejected: list[dict[str, Any]] = []
        seen = {"n": 0, "first": True}

        async def reject(index: int, reason: str) -> None:
            rejected.append({"index": index, "reason": reason})
            CLAIMS_REJECTED.labels(reason=reason).inc()
            await emit("claim_rejected", {"index": index, "reason": reason})

        async def handle(raw: dict[str, Any]) -> None:
            index = seen["n"]
            seen["n"] += 1
            try:
                claim = Claim.model_validate(raw)
            except ValidationError:
                await reject(index, "schema_invalid")
                return
            if len(verified) >= MAX_CLAIMS:
                await reject(index, "schema_invalid")
                return
            if not check_output(claim.text, context_texts).ok:
                await reject(index, "output_guard")
                return
            vc, reason = verify_claim(claim, by_id, numbering, len(verified))
            if vc is None:
                await reject(index, reason or "quote_not_found")
                return
            verified.append(vc)
            CLAIMS_VERIFIED.inc()
            if seen["first"]:
                seen["first"] = False
                TTFT_SECONDS.observe(time.perf_counter() - RUN_STARTED.get())
            payload = vc.model_dump()
            await emit("claim", payload)
            words = payload["text"].split(" ")
            for i in range(0, len(words), 6):
                piece = " ".join(words[i : i + 6]) + (" " if i + 6 < len(words) else "")
                await emit("token", {"claim_index": payload["index"], "text": piece})

        async def on_text(delta: str) -> None:
            for raw in parser.feed(delta):
                await handle(raw)

        result: LLMResult | None = None
        truncated = False
        try:
            result = await deps.gateway.stream(req, on_text=on_text)
        except LLMRefusal:
            for vc in verified:  # never leave claims on screen that the final answer will not contain
                await emit("claim_rejected", {"index": vc.index, "reason": "retracted"})
            return {
                "abstained": True,
                "abstain_reason": "refusal",
                "draft": None,
                "_steps": [
                    make_step(state["run_id"], "llm:generate", kind="llm", status="error", error="refusal"),
                    *await _skip(state["run_id"], "verify_citations"),
                ],
            }
        except LLMMaxTokens:
            truncated = True
        steps = []
        cost = state.get("cost_usd", 0.0)
        draft_answer = ""
        model_abstained = False
        if result is not None:
            cost += result.cost_usd
            steps.append(
                make_step(
                    state["run_id"],
                    "llm:generate",
                    kind="llm",
                    model=result.model,
                    prompt_version=version,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                    latency_ms=result.latency_ms,
                )
            )
            parsed = result.parsed or {}
            draft_answer = str(parsed.get("answer") or "")[:1200]
            model_abstained = bool(parsed.get("abstained")) and not verified
        else:
            steps.append(
                make_step(state["run_id"], "llm:generate", kind="llm", status="error", error="max_tokens")
            )
        draft = {
            "answer": draft_answer,
            "abstained": model_abstained,
            "truncated": truncated,
            "claims": [c.model_dump() for c in verified],
            "rejected": rejected,
        }
        if not verified:
            return {
                "abstained": True,
                "abstain_reason": "no_verified_claims",
                "draft": draft,
                "cost_usd": cost,
                "_steps": [*steps, *await _skip(state["run_id"], "verify_citations")],
            }
        return {"draft": draft, "cost_usd": cost, "_steps": steps}

    @_node("verify_citations")
    async def verify_node(state: GraphState) -> dict[str, Any]:
        """Assemble the final answer from the claims verified while streaming (re-checked here)."""
        draft = state["draft"] or {}
        claims = [VerifiedClaim.model_validate(c) for c in draft.get("claims", [])]
        by_id = {c["chunk_id"]: c for c in state["context"]}
        # defence in depth: every quote must still be in the context that was given to the model
        claims = [
            c
            for c in claims
            if all(
                cit.chunk_id in by_id and locate(cit.quote, by_id[cit.chunk_id]["text"])
                for cit in c.citations
            )
        ]
        if not claims:
            return {"abstained": True, "abstain_reason": "no_verified_claims"}
        answer = final_answer(str(draft.get("answer", "")), claims)
        if not check_output(answer, [c["text"] for c in state["context"]]).ok:
            answer = " ".join(c.text for c in claims)
        verified = VerifiedAnswer(
            claims=claims, answer=answer, rejected=draft.get("rejected", []), abstained=False
        )
        return {"verified": verified.model_dump()}

    def _history_entry(state: GraphState) -> dict[str, Any]:
        titles = sorted({c.get("title", "") for c in (state.get("context") or [])[:3] if c.get("title")})
        return {
            "run_id": state["run_id"],
            "sub": state["principal"]["sub"],
            "question": state["standalone_question"],
            "titles": titles,
        }

    @_node("respond")
    async def respond(state: GraphState) -> dict[str, Any]:
        return {"history": [_history_entry(state)]}

    @_node("abstain")
    async def abstain(state: GraphState) -> dict[str, Any]:
        reason = state.get("abstain_reason") or "no_verified_claims"
        ABSTENTIONS.labels(reason=reason).inc()
        return {"abstained": True, "abstain_reason": reason, "history": [_history_entry(state)]}

    def after_principal(state: GraphState) -> str:
        return "condense_followup" if state.get("follow_up_of") else "retrieve"

    def after_sufficiency(state: GraphState) -> str:
        return "abstain" if state.get("abstained") else "generate"

    def after_generate(state: GraphState) -> str:
        return "abstain" if state.get("abstained") else "verify_citations"

    def after_verify(state: GraphState) -> str:
        return "abstain" if state.get("abstained") else "respond"

    g = StateGraph(GraphState)
    for fn in (
        resolve_principal,
        condense_followup,
        retrieve,
        fuse,
        rerank,
        guard_context,
        check_sufficiency,
        generate,
        verify_node,
        respond,
        abstain,
    ):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "resolve_principal")
    g.add_conditional_edges("resolve_principal", after_principal, ["condense_followup", "retrieve"])
    g.add_edge("condense_followup", "retrieve")
    g.add_edge("retrieve", "fuse")
    g.add_edge("fuse", "rerank")
    g.add_edge("rerank", "guard_context")
    g.add_edge("guard_context", "check_sufficiency")
    g.add_conditional_edges("check_sufficiency", after_sufficiency, ["generate", "abstain"])
    g.add_conditional_edges("generate", after_generate, ["verify_citations", "abstain"])
    g.add_conditional_edges("verify_citations", after_verify, ["respond", "abstain"])
    g.add_edge("respond", END)
    g.add_edge("abstain", END)
    return g.compile(checkpointer=checkpointer)


async def run_graph(
    graph: Any,
    *,
    question: str,
    principal: Principal,
    as_of: str,
    conversation_id: str | None = None,
    follow_up_of: str | None = None,
    run_id: str | None = None,
    emit: Emit | None = None,
) -> dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    conversation_id = conversation_id or str(uuid.uuid4())
    token = EMIT.set(emit)
    started = time.perf_counter()
    started_token = RUN_STARTED.set(started)
    try:
        state = await graph.ainvoke(
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "question": question,
                "follow_up_of": follow_up_of,
                "as_of": as_of,
                "principal": principal,
            },
            config={"configurable": {"thread_id": conversation_id}},
            durability="exit",
        )
    finally:
        EMIT.reset(token)
        RUN_STARTED.reset(started_token)
    out = dict(state)
    out["steps"] = [s for s in out.get("steps", []) if s["run_id"] == run_id]
    out["latency_ms"] = (time.perf_counter() - started) * 1000
    return out


__all__ = ["GraphDeps", "build_graph", "build_response", "run_graph"]
