"""Structured JSON logs (structlog) with ``correlation_id`` and ``run_id`` (BUILD.md §14).

Question, answer, quote, comment and document text never reach a log line: those keys are replaced by
``[redacted]`` whatever the call site passes.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACTED_KEYS = frozenset(
    {"question", "text", "quote", "answer", "comment", "chunk_text", "standalone_question"}
)


def _redact(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in REDACTED_KEYS & event.keys():
        event[key] = "[redacted]"
    return event


def _add_service(service: str) -> Any:
    def add(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        event.setdefault("service", service)
        return event

    return add


def configure_logging(level: str = "INFO", *, service: str = "api") -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            _add_service(service),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),  # resolves sys.stdout per logger, not once
        cache_logger_on_first_use=False,
    )


def bind_correlation(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def bind_run(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
