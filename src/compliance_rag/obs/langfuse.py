"""Langfuse reporting (compose profile ``langfuse``): one ``generation-create`` per LLM call through the public
ingestion API. Numbers and ids only (route, model, prompt version, tokens, cost, latency, outcome) — never
prompt, document or answer text. Best effort: failures are logged by type and never reach the caller.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from compliance_rag.llm.gateway import LLMResult

log = structlog.get_logger(__name__)


class LangfuseReporter:
    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client = httpx.AsyncClient(
            base_url=host.rstrip("/"), auth=(public_key, secret_key), timeout=5.0, transport=transport
        )

    async def report(self, result: LLMResult, *, run_id: str | None) -> None:
        end = datetime.now(UTC)
        start = end - timedelta(milliseconds=result.latency_ms)
        event_id = uuid.uuid4().hex
        body: dict[str, Any] = {
            "id": event_id,
            "traceId": run_id or event_id,
            "name": result.route,
            "model": result.model,
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
            "usage": {"input": result.input_tokens, "output": result.output_tokens, "unit": "TOKENS"},
            "metadata": {
                "prompt": result.prompt_name,
                "prompt_version": result.prompt_version,
                "cost_usd": result.cost_usd,
                "latency_ms": round(result.latency_ms, 1),
                "stop_reason": result.stop_reason,
                "outcome": result.outcome,
                "from_cassette": result.from_cassette,
            },
        }
        batch = {
            "batch": [
                {
                    "id": uuid.uuid4().hex,
                    "type": "generation-create",
                    "timestamp": end.isoformat(),
                    "body": body,
                }
            ]
        }
        try:
            resp = await self.client.post("/api/public/ingestion", json=batch)
            if resp.status_code >= 300 and resp.status_code != 207:
                log.warning("langfuse_rejected", status=resp.status_code)
        except Exception as exc:  # best effort: never an unretrieved task exception, only the type is logged
            log.warning("langfuse_unavailable", error=type(exc).__name__)

    async def close(self) -> None:
        await self.client.aclose()
