"""Structured JSON logs (structlog) with ``correlation_id`` and ``run_id`` (BUILD.md §14).

Question, answer, quote, comment, prompt and document text never reach a log line: those keys are replaced by
``[redacted]`` at any depth, whatever the call site passes. Standard-library loggers (uvicorn, httpx, arq)
go through the same processors, so they are JSON and redacted too.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACTED_KEYS = frozenset(
    {
        "question",
        "standalone_question",
        "text",
        "chunk_text",
        "quote",
        "answer",
        "comment",
        "query",
        "q",
        "prompt",
        "content",
        "context",
        "claims",
        "title",
    }
)
REDACTED = "[redacted]"


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if k in REDACTED_KEYS else _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v) for v in value]
    return value


def _redact(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key in REDACTED_KEYS:
            event[key] = REDACTED
        elif key != "event":
            event[key] = _scrub(event[key])
    return event


def _add_service(service: str) -> Any:
    def add(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        event.setdefault("service", service)
        return event

    return add


def _shared(service: str) -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        _add_service(service),
    ]


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever ``sys.stdout`` is at emit time (test runners and reloaders swap it)."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


class _RedactExtras(logging.Filter):
    """stdlib ``extra={...}`` fields become record attributes: drop the text-bearing ones."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in REDACTED_KEYS & record.__dict__.keys():
            setattr(record, key, REDACTED)
        return True


def configure_logging(level: str = "INFO", *, service: str = "api") -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            *_shared(service),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),  # resolves sys.stdout per logger, not once
        cache_logger_on_first_use=False,
    )
    handler = _StdoutHandler(sys.stdout)
    handler.addFilter(_RedactExtras())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.ExtraAdder(),
                *_shared(service),
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric)


def bind_correlation(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def bind_run(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
