"""Structured JSON logs (structlog) with ``correlation_id`` and ``run_id`` (BUILD.md §14).

Question, answer, quote, comment, prompt and document text never reach a log line: those keys are replaced by
``[redacted]`` at any depth, whatever the call site passes, and exceptions are rendered as their types and
frames without messages. Standard-library loggers (uvicorn, httpx, arq)
go through the same processors, so they are JSON and redacted too; libraries outside ``APP_LOGGERS`` (provider
SDKs, HTTP clients) only emit WARNING and above, since their DEBUG/INFO messages embed request bodies and URLs.
"""

from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import MutableMapping
from types import TracebackType
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
        elif key not in ("event", "exc_info"):
            event[key] = _scrub(event[key])
    return event


def _exception(value: Any) -> BaseException | None:
    if value is True:
        value = sys.exc_info()
    if isinstance(value, BaseException):
        return value
    if isinstance(value, tuple | list) and len(value) == 3 and isinstance(value[1], BaseException):
        return value[1]
    return None


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return seen


def _type_and_frames(exc: BaseException) -> str:
    parts = []
    for item in reversed(_chain(exc)):  # outermost last, like Python's own traceback
        tb: TracebackType | None = item.__traceback__
        frames = "".join(  # file, line and function; no source text
            f'  File "{f.filename}", line {f.lineno}, in {f.name}\n'
            for f in traceback.StackSummary.extract(traceback.walk_tb(tb), lookup_lines=False)
        )
        name = type(item).__qualname__
        module = type(item).__module__
        parts.append(
            f"Traceback (most recent call last):\n{frames}{name if module == 'builtins' else f'{module}.{name}'}"
        )
    return "\n\nThe above exception led to:\n\n".join(parts)


_TRACEBACK = "Traceback (most recent call last):"
_FRAME = re.compile(r'^\s*File "[^"]*", line \d+(?:, in .*)?$')
_EXCEPTION_LINE = re.compile(r"^([A-Za-z_][\w.]*)(?::.*)?$")
_CHAIN = ("During handling of the above exception", "The above exception was the direct cause")


def _traceback_text_without_messages(text: str) -> str:
    """A traceback logged as text (uvicorn's lifespan does): keep the header, frame lines and exception types;
    drop source lines, messages and anything after them (``DETAIL:`` lines, notes)."""
    head, _, tail = text.partition(_TRACEBACK)
    kept = [head.rstrip()] if head.strip() else []
    for line in (_TRACEBACK + tail).splitlines():
        if line.startswith(_TRACEBACK) or line.startswith(_CHAIN) or _FRAME.match(line):
            kept.append(line)
        elif not line.startswith((" ", "\t")) and (match := _EXCEPTION_LINE.match(line)):
            kept.append(match.group(1))  # `psycopg.errors.UniqueViolation: ...` keeps the type only
    return "\n".join(kept)


def _exceptions_without_messages(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Exceptions as type and frames only: their messages can hold row values (psycopg ``DETAIL``), request
    input (pydantic ``input_value``) or document text, also where a library puts them into its own message."""
    exc = _exception(event.pop("exc_info", None))
    message = event.get("event")
    if isinstance(message, str) and _TRACEBACK in message:
        event["event"] = _traceback_text_without_messages(message)
    if exc is None:
        return event
    message = event.get("event")
    if isinstance(message, str):
        for item in _chain(exc):
            text = str(item)
            if text:
                message = message.replace(text, REDACTED)
        event["event"] = message
    event["exception"] = _type_and_frames(exc)
    return event


def error_label(exc: BaseException) -> str:
    """What may be stored or shown about a failure (job rows, inbox error files): the type and SQLSTATE."""
    sqlstate = getattr(exc, "sqlstate", None)
    name = type(exc).__name__
    return f"{name} (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) and sqlstate else name


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


# loggers whose INFO/DEBUG records are ours to emit; every other library is held at WARNING, because provider
# SDKs and HTTP clients log whole request bodies and URLs (prompt, chunks, question) in formatted messages
APP_LOGGERS = ("compliance_rag", "evalgate", "arq", "uvicorn")


class _ThirdPartyAtWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        if record.name == "uvicorn.access":  # its INFO lines carry query strings (titles, search terms)
            return False
        return any(record.name == name or record.name.startswith(f"{name}.") for name in APP_LOGGERS)


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
            _exceptions_without_messages,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),  # resolves sys.stdout per logger, not once
        cache_logger_on_first_use=False,
    )
    handler = _StdoutHandler(sys.stdout)
    handler.addFilter(_ThirdPartyAtWarning())
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
                _exceptions_without_messages,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):  # uvicorn installs its own plain handlers
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def bind_correlation(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def bind_run(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
