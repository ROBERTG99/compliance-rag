"""LLM gateway: stop reasons, retries, cassettes, PII redaction, accounting (T-22, T-23)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from compliance_rag.llm.cassette import CassetteMismatch, cassette_key
from compliance_rag.llm.gateway import (
    Gateway,
    GenerationUnavailable,
    LLMMaxTokens,
    LLMRefusal,
    LLMRequest,
    estimate_cost,
)
from compliance_rag.settings import Settings

SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "string"}},
    "required": ["x"],
    "additionalProperties": False,
}


class FakeStream:
    def __init__(self, message: Any, texts: list[str]) -> None:
        self.message, self.texts = message, texts

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> Any:
        async def gen() -> Any:
            for t in self.texts:
                yield t

        return gen()

    async def get_final_message(self) -> Any:
        return self.message


def _message(stop_reason: str, text: str = '{"x": "ok"}') -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber", explanation="declined")
        if stop_reason == "refusal"
        else None,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=1000, output_tokens=200, cache_read_input_tokens=800, cache_creation_input_tokens=0
        ),
        model="claude-opus-5-5",
    )


class SpyClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeStream(outcome, [outcome.content[1].text])


def _gateway(client: SpyClient, tmp_path: Path, **kw: Any) -> Gateway:
    settings = Settings(
        _env_file=None, llm_provider="anthropic", demo_mode="live", cassette_dir=str(tmp_path), **kw
    )
    return Gateway(settings, client=client)


def _req(user: str = "question") -> LLMRequest:
    return LLMRequest(
        route="generate",
        system="SYSTEM PREFIX",
        user=user,
        schema=SCHEMA,
        schema_name="t",
        prompt_name="generate_answer",
        prompt_version="v1",
    )


async def test_refusal_and_max_tokens_handled(tmp_path: Path) -> None:
    gw = _gateway(SpyClient([_message("refusal"), _message("max_tokens", '{"x": "trunc')]), tmp_path)
    with pytest.raises(LLMRefusal) as refusal:
        await gw.complete(_req())
    assert refusal.value.category == "cyber"
    with pytest.raises(LLMMaxTokens):
        await gw.complete(_req())


async def test_request_shape_caching_effort_and_schema(tmp_path: Path) -> None:
    client = SpyClient([_message("end_turn")])
    result = await _gateway(client, tmp_path).complete(_req())
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "budget_tokens" not in json.dumps(call) and "tool_choice" not in call
    assert result.parsed == {"x": "ok"}
    assert result.input_tokens == 1000 and result.output_tokens == 200
    assert result.cost_usd == pytest.approx(estimate_cost("claude-opus-5-5", 1000, 200, cache_read=800))
    assert result.prompt_version == "v1" and result.outcome == "ok"


async def test_pii_never_reaches_the_provider(tmp_path: Path) -> None:
    client = SpyClient([_message("end_turn")])
    await _gateway(client, tmp_path).complete(
        _req("Email jane.doe@example.com, call +44 20 7946 0958, IBAN DE89 3704 0044 0532 0130 00")
    )
    payload = json.dumps(client.calls[0], default=str)
    for secret in ("jane.doe@example.com", "7946 0958", "DE89 3704"):
        assert secret not in payload
    assert "[EMAIL]" in payload


async def test_non_retryable_errors_surface_and_retryable_become_unavailable(tmp_path: Path) -> None:
    import anthropic

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad = anthropic.BadRequestError("bad", response=httpx.Response(400, request=request), body=None)
    overloaded = anthropic.InternalServerError(
        "overloaded", response=httpx.Response(529, request=request), body=None
    )
    gw = _gateway(SpyClient([bad]), tmp_path)
    with pytest.raises(anthropic.BadRequestError):
        await gw.complete(_req())
    gw = _gateway(SpyClient([overloaded]), tmp_path)
    with pytest.raises(GenerationUnavailable):
        await gw.complete(_req())


async def test_cassette_overrides_provider_and_detects_mismatch(tmp_path: Path) -> None:
    req = _req()
    settings = Settings(_env_file=None, cassette_dir=str(tmp_path))
    gw = Gateway(settings)  # fake provider
    key, digest = cassette_key(
        req.route, settings.model_generate, req.prompt_version, gw.messages_for(req), req.schema_name
    )
    path = tmp_path / "generate" / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "key": key,
                "route": "generate",
                "model": settings.model_generate,
                "prompt_version": "v1",
                "request_digest": digest,
                "response": '{"x": "from cassette"}',
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "recorded_at": "2026-10-16",
            }
        )
    )
    result = await gw.complete(req)
    assert result.parsed == {"x": "from cassette"} and result.from_cassette
    data = json.loads(path.read_text())
    data["request_digest"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(CassetteMismatch):
        await gw.complete(req)


async def test_fake_provider_requires_no_key(tmp_path: Path) -> None:
    gw = Gateway(Settings(_env_file=None, cassette_dir=str(tmp_path)))
    result = await gw.complete(
        LLMRequest(
            route="generate",
            system="s",
            user="u",
            schema=None,
            schema_name="generated_answer",
            prompt_name="generate_answer",
            prompt_version="v1",
            data={
                "question": "What is the daily limit for the Orion card?",
                "context": [{"chunk_id": "a" * 32, "text": "The daily limit for the Orion card is EUR 500."}],
            },
        )
    )
    assert result.model == "fake" and result.cost_usd == 0.0
    assert result.parsed and result.parsed["claims"][0]["citations"][0]["chunk_id"] == "a" * 32
