"""Recorded LLM responses (cassette.v1): ``tests/fixtures/llm/<route>/<key>.json``.

``key = sha256(route | model | prompt_version | canonical_json(messages, schema_name))``; the stored
``request_digest`` must match the request or ``CassetteMismatch`` is raised.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CassetteMismatch(RuntimeError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_digest(messages: Any, schema_name: str) -> str:
    return hashlib.sha256(canonical([messages, schema_name]).encode()).hexdigest()


def cassette_key(
    route: str, model: str, prompt_version: str, messages: Any, schema_name: str
) -> tuple[str, str]:
    digest = request_digest(messages, schema_name)
    key = hashlib.sha256(f"{route}|{model}|{prompt_version}|{digest}".encode()).hexdigest()
    return key, digest


class CassetteStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, route: str, key: str) -> Path:
        return self.root / route / f"{key}.json"

    def load(self, route: str, key: str, digest: str) -> dict[str, Any] | None:
        path = self.path(route, key)
        if not path.is_file():
            return None
        data: dict[str, Any] = json.loads(path.read_text())
        if data.get("request_digest") != digest:
            raise CassetteMismatch(f"cassette {path} does not match the request")
        return data

    def save(
        self,
        route: str,
        key: str,
        digest: str,
        model: str,
        prompt_version: str,
        response: str,
        usage: dict[str, int],
    ) -> Path:
        path = self.path(route, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "key": key,
                    "route": route,
                    "model": model,
                    "prompt_version": prompt_version,
                    "request_digest": digest,
                    "response": response,
                    "usage": usage,
                    "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return path
