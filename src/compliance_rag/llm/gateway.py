"""LLM gateway — the only module that imports provider SDKs (``anthropic``, ``openai``, Bedrock runtime).

Responsibilities (BUILD.md Appendix B): provider selection (FakeLLM offline, Anthropic, Claude on
Bedrock via ``AnthropicBedrockMantle``), cassettes, PII redaction before any provider call, adaptive
thinking with an explicit effort per route, JSON-schema structured output, streaming, prompt caching of
the stable system prefix, ``stop_reason`` checks (``refusal`` → ``LLMRefusal``, ``max_tokens`` →
``LLMMaxTokens``), typed errors (retryable ones surface as ``GenerationUnavailable`` after the SDK's
own backoff-with-jitter retries), timeouts, token/cost accounting and metrics.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml
from opentelemetry.trace import SpanKind, Status, StatusCode

from compliance_rag.guard.pii import redact
from compliance_rag.llm.cassette import CassetteStore, cassette_key
from compliance_rag.llm.fake import FakeLLM
from compliance_rag.obs.metrics import LLM_COST, LLM_TOKENS
from compliance_rag.obs.tracing import tracer
from compliance_rag.settings import Settings, get_settings

ROUTING_FILE = Path(__file__).with_name("routing.yaml")
MAX_REPORTS_IN_FLIGHT = 64  # Langfuse reports pending at once; beyond it reports are dropped, never queued
log = structlog.get_logger(__name__)


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    def __init__(self, category: str | None, explanation: str | None = None) -> None:
        super().__init__(f"model refused ({category})")
        self.category = category
        self.explanation = explanation


class LLMMaxTokens(LLMError):
    pass


class GenerationUnavailable(LLMError):
    """Provider unavailable after retries (429/5xx/connection/timeout)."""


@dataclass(frozen=True)
class Route:
    name: str
    model_setting: str
    effort: str
    max_tokens: int
    timeout_s: float


@lru_cache(maxsize=1)
def _routing() -> dict[str, Any]:
    return dict(yaml.safe_load(ROUTING_FILE.read_text()))


def route_config(name: str) -> Route:
    r = _routing()["routes"][name]
    return Route(name, r["model_setting"], r["effort"], int(r["max_tokens"]), float(r["timeout_s"]))


_BEDROCK_ID = re.compile(r"^(?:(?:us|eu|apac|global)\.)?(?:anthropic\.)?(?P<name>.+?)(?:-v\d+:\d+)?$")


def _price_key(model: str) -> str:
    """Bedrock ids (`us.anthropic.claude-opus-5-5-v1:0`) and plain ids share one price entry."""
    match = _BEDROCK_ID.match(model)
    return match.group("name") if match else model


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> float:
    price = _routing()["pricing"].get(_price_key(model))
    if not price:
        return 0.0
    uncached = max(0, input_tokens)
    return float(
        round(
            (
                uncached * price["input"]
                + output_tokens * price["output"]
                + cache_read * price["cache_read"]
                + cache_write * price["cache_write"]
            )
            / 1_000_000,
            6,
        )
    )


@dataclass
class LLMRequest:
    route: str
    system: str
    user: str
    schema: dict[str, Any] | None
    schema_name: str
    prompt_name: str
    prompt_version: str
    data: dict[str, Any] = field(default_factory=dict)  # structured inputs for the offline fake


@dataclass
class LLMResult:
    text: str
    parsed: dict[str, Any] | None
    model: str
    route: str
    prompt_name: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    stop_reason: str
    outcome: str
    from_cassette: bool = False


def _parse(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class Gateway:
    def __init__(
        self, settings: Settings | None = None, client: Any | None = None, fake: FakeLLM | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.fake = fake or FakeLLM()
        self._client = client
        self.cassettes = CassetteStore(Path(self.settings.cassette_dir))
        self._langfuse: Any = None
        self._reports: set[asyncio.Task[None]] = set()

    def _report(self, result: LLMResult) -> None:
        """Langfuse (profile ``langfuse``) when configured: fire and forget, numbers only, never fails the call."""
        s = self.settings
        if not (s.langfuse_host and s.langfuse_public_key and s.langfuse_secret_key):
            return
        if len(self._reports) >= MAX_REPORTS_IN_FLIGHT:
            log.warning("langfuse_report_dropped", in_flight=len(self._reports))
            return
        try:
            if self._langfuse is None:
                from compliance_rag.obs.langfuse import LangfuseReporter

                self._langfuse = LangfuseReporter(
                    s.langfuse_host, s.langfuse_public_key, s.langfuse_secret_key.get_secret_value()
                )
            run_id = structlog.contextvars.get_contextvars().get("run_id")
            task = asyncio.create_task(self._langfuse.report(result, run_id=run_id))
        except Exception as exc:  # reporting is best effort: the LLM call itself succeeded
            log.warning("langfuse_unavailable", error=type(exc).__name__)
            return
        self._reports.add(task)
        task.add_done_callback(self._reports.discard)

    async def aclose(self) -> None:
        """Let pending reports finish (briefly), then close the reporter's HTTP client."""
        if self._reports:
            _, pending = await asyncio.wait(set(self._reports), timeout=5.0)
            for task in pending:
                task.cancel()
        if self._langfuse is not None:
            await self._langfuse.close()
            self._langfuse = None

    # -- provider ------------------------------------------------------------------------------
    @property
    def provider(self) -> str:
        if self.settings.demo_mode == "offline" and self._client is None:
            return "fake"
        return self.settings.llm_provider

    def _anthropic(self) -> Any:
        if self._client is not None:
            return self._client
        import anthropic

        if self.settings.llm_provider == "bedrock":
            self._client = anthropic.AsyncAnthropicBedrockMantle(
                aws_region=self.settings.aws_region, max_retries=3
            )
        else:
            key = self.settings.anthropic_api_key
            self._client = anthropic.AsyncAnthropic(
                api_key=key.get_secret_value() if key and key.get_secret_value() else None, max_retries=3
            )
        return self._client

    def model_for(self, route: Route) -> str:
        model = str(getattr(self.settings, route.model_setting))
        if self.settings.llm_provider == "bedrock" and not model.startswith("anthropic."):
            model = f"anthropic.{model}"
        return model

    @staticmethod
    def messages_for(req: LLMRequest) -> list[dict[str, Any]]:
        return [{"role": "user", "content": redact(req.user)}]

    def _params(self, req: LLMRequest, route: Route, model: str) -> dict[str, Any]:
        output_config: dict[str, Any] = {"effort": route.effort}
        if req.schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": req.schema}
        return {
            "model": model,
            "max_tokens": route.max_tokens,
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": self.messages_for(req),
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }

    # -- public API ----------------------------------------------------------------------------
    async def stream(self, req: LLMRequest, on_text: Callable[[str], Any] | None = None) -> LLMResult:
        """Run a request; ``on_text`` receives text deltas as they arrive (provider) or once (fake).

        One ``gen_ai.<route>`` span per call with the GenAI semantic-convention attributes (never prompt text).
        """
        with tracer.start_as_current_span(f"gen_ai.{req.route}", kind=SpanKind.CLIENT) as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", {"bedrock": "aws.bedrock"}.get(self.provider, self.provider))
            span.set_attribute("app.route", req.route)
            span.set_attribute("app.prompt", req.prompt_name)
            span.set_attribute("app.prompt_version", str(req.prompt_version))
            try:
                result = await self._stream(req, on_text)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                raise
            span.set_attribute("gen_ai.request.model", result.model)
            span.set_attribute("gen_ai.response.finish_reasons", [result.stop_reason])
            span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
            span.set_attribute("app.cost_usd", result.cost_usd)
            span.set_attribute("app.from_cassette", result.from_cassette)
            self._report(result)
            return result

    async def _stream(self, req: LLMRequest, on_text: Callable[[str], Any] | None = None) -> LLMResult:
        route = route_config(req.route)
        started = time.perf_counter()
        model = "fake" if self.provider == "fake" else self.model_for(route)
        cassette_model = self.model_for(route)
        key, digest = cassette_key(
            req.route, cassette_model, req.prompt_version, self.messages_for(req), req.schema_name
        )
        recorded = self.cassettes.load(req.route, key, digest)
        if recorded is not None:
            text = str(recorded["response"])
            if on_text:
                await _maybe_await(on_text(text))
            usage = recorded.get("usage", {})
            return self._result(
                req,
                cassette_model,
                text,
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                0,
                started,
                "end_turn",
                from_cassette=True,
            )
        if self.provider == "fake":
            text = self.fake.respond(req.route, req.data)
            if on_text:
                await _maybe_await(on_text(text))
            return self._result(req, "fake", text, 0, 0, 0, started, "end_turn")
        try:
            return await asyncio.wait_for(
                self._provider_call(req, route, model, key, digest, on_text, started), timeout=route.timeout_s
            )
        except TimeoutError as exc:
            raise GenerationUnavailable(f"{req.route} timed out after {route.timeout_s}s") from exc

    async def complete(self, req: LLMRequest) -> LLMResult:
        return await self.stream(req)

    async def _provider_call(
        self,
        req: LLMRequest,
        route: Route,
        model: str,
        key: str,
        digest: str,
        on_text: Callable[[str], Any] | None,
        started: float,
    ) -> LLMResult:
        import anthropic

        client = self._anthropic()
        params = self._params(req, route, model)
        try:
            async with client.messages.stream(**params) as stream:
                async for delta in stream.text_stream:
                    if on_text:
                        await _maybe_await(on_text(delta))
                message = await stream.get_final_message()
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as exc:
            raise GenerationUnavailable(f"{type(exc).__name__}: provider unavailable") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (408, 409) or exc.status_code >= 500:
                raise GenerationUnavailable(f"provider error {exc.status_code}") from exc
            raise
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise LLMRefusal(getattr(details, "category", None), getattr(details, "explanation", None))
        if message.stop_reason == "max_tokens":
            raise LLMMaxTokens(f"{req.route} hit max_tokens={route.max_tokens}")
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        usage = message.usage
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        result = self._result(
            req,
            model,
            text,
            int(usage.input_tokens),
            int(usage.output_tokens),
            cache_read,
            started,
            str(message.stop_reason),
            cache_write=cache_write,
        )
        if self.settings.record_cassettes:
            self.cassettes.save(
                req.route,
                key,
                digest,
                model,
                req.prompt_version,
                text,
                {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
            )
        return result

    def _result(
        self,
        req: LLMRequest,
        model: str,
        text: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        started: float,
        stop_reason: str,
        from_cassette: bool = False,
        cache_write: int = 0,
    ) -> LLMResult:
        cost = (
            0.0
            if model == "fake" or from_cassette
            else estimate_cost(model, input_tokens, output_tokens, cache_read, cache_write)
        )
        if model != "fake":
            LLM_TOKENS.labels(route=req.route, model=model, direction="input").inc(input_tokens)
            LLM_TOKENS.labels(route=req.route, model=model, direction="output").inc(output_tokens)
            LLM_COST.labels(route=req.route, model=model).inc(cost)
        parsed = _parse(text)
        return LLMResult(
            text=text,
            parsed=parsed,
            model=model,
            route=req.route,
            prompt_name=req.prompt_name,
            prompt_version=req.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=(time.perf_counter() - started) * 1000,
            stop_reason=stop_reason,
            outcome="ok" if parsed is not None or req.schema is None else "invalid_json",
            from_cassette=from_cassette,
        )


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value


async def iter_text(chunks: list[str]) -> AsyncIterator[str]:  # pragma: no cover - helper for callers
    for c in chunks:
        yield c


class RedactingBedrockRuntime:
    """Wraps a ``bedrock-runtime`` client: redacts PII in Titan/Cohere request bodies, records usage."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def invoke_model(self, **kwargs: Any) -> Any:
        body = json.loads(kwargs.get("body") or "{}")
        if isinstance(body.get("inputText"), str):
            body["inputText"] = redact(body["inputText"])
        if isinstance(body.get("query"), str):
            body["query"] = redact(body["query"])
        if isinstance(body.get("documents"), list):
            body["documents"] = [redact(d) if isinstance(d, str) else d for d in body["documents"]]
        kwargs["body"] = json.dumps(body)
        resp = self._client.invoke_model(**kwargs)
        model = str(kwargs.get("modelId", "bedrock"))
        LLM_TOKENS.labels(route="embed_or_rerank", model=model, direction="input").inc(
            len(json.dumps(body)) // 4  # coarse estimate; Bedrock bills per token or search unit
        )
        return resp


class RedactingOpenAI:
    """Wraps an OpenAI client so ``embeddings.create`` never sends PII."""

    def __init__(self, client: Any) -> None:
        self._client = client
        outer = self

        class _Embeddings:
            def create(self, **kwargs: Any) -> Any:
                inputs = kwargs.get("input")
                if isinstance(inputs, list):
                    kwargs["input"] = [redact(t) if isinstance(t, str) else t for t in inputs]
                elif isinstance(inputs, str):
                    kwargs["input"] = redact(inputs)
                resp = outer._client.embeddings.create(**kwargs)
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    LLM_TOKENS.labels(route="embed", model=str(kwargs.get("model")), direction="input").inc(
                        int(getattr(usage, "prompt_tokens", 0) or 0)
                    )
                return resp

        self.embeddings = _Embeddings()


def bedrock_runtime_client() -> Any:
    import boto3

    return RedactingBedrockRuntime(boto3.client("bedrock-runtime", region_name=get_settings().aws_region))


def openai_client() -> Any:
    import openai

    key = get_settings().openai_api_key
    return RedactingOpenAI(openai.OpenAI(api_key=key.get_secret_value() if key else None))
