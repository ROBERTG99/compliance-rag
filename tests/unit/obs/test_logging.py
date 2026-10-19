"""JSON logs with correlation and run ids; never question or document text (BUILD.md §14, T-43)."""

from __future__ import annotations

import json

import pytest
import structlog

from compliance_rag.obs.logging import bind_correlation, bind_run, clear_context, configure_logging


def test_json_lines_carry_correlation_and_run_ids(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", service="api")
    clear_context()
    bind_correlation("req-123")
    bind_run("run-9")
    structlog.get_logger("t").info("ask_accepted", persona="analyst")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "ask_accepted"
    assert line["correlation_id"] == "req-123" and line["run_id"] == "run-9"
    assert line["service"] == "api" and line["level"] == "info" and "timestamp" in line
    clear_context()


def test_text_fields_are_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", service="api")
    clear_context()
    structlog.get_logger("t").warning(
        "oops",
        question="What is the litigation hold period?",
        text="Complaint files under a litigation hold are kept 7 years.",
        quote="kept 7 years",
        answer="7 years",
        comment="free text",
        chunk_id="c" * 32,
    )
    raw = capsys.readouterr().out
    line = json.loads(raw.strip().splitlines()[-1])
    for key in ("question", "text", "quote", "answer", "comment"):
        assert line[key] == "[redacted]"
    assert line["chunk_id"] == "c" * 32
    assert "litigation" not in raw and "7 years" not in raw


def test_nested_values_and_more_keys_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", service="api")
    structlog.get_logger("t").info(
        "nested",
        details={"query": "litigation hold", "claims": [{"text": "kept 7 years"}]},
        prompt="secret prompt",
    )
    raw = capsys.readouterr().out
    assert "litigation" not in raw and "7 years" not in raw and "secret prompt" not in raw


def test_stdlib_loggers_go_through_the_same_json_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    configure_logging("INFO", service="api")
    logging.getLogger("httpx").warning("request failed", extra={"question": "What is the litigation hold?"})
    out = capsys.readouterr()
    line = json.loads((out.out + out.err).strip().splitlines()[-1])
    assert line["event"] == "request failed" and line["logger"] == "httpx" and line["service"] == "api"
    assert "litigation" not in out.out + out.err


def test_third_party_debug_records_never_reach_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    # provider SDKs log whole request bodies (system prompt, <document> chunks, question) at DEBUG; the
    # redaction works on keys, not on formatted messages, so their DEBUG/INFO records must not be emitted
    import logging

    configure_logging("DEBUG", service="api")
    body = {"messages": [{"content": "<document>Complaint files under a litigation hold</document>"}]}
    logging.getLogger("anthropic._base_client").debug("Request options: %s", body)
    logging.getLogger("botocore.endpoint").debug("Making request %s", body)
    logging.getLogger("httpx").info("HTTP Request: POST https://api.example/v1/messages?q=litigation")
    logging.getLogger("uvicorn.access").info('"GET /v1/documents?q=litigation HTTP/1.1" 200')
    logging.getLogger("compliance_rag.retrieval").debug("leg finished", extra={"leg": "bm25"})
    logging.getLogger("anthropic._base_client").warning("retrying request")
    out = capsys.readouterr()
    raw = out.out + out.err
    assert "litigation" not in raw
    events = [json.loads(line) for line in raw.strip().splitlines()]
    assert [(e["logger"], e["event"]) for e in events] == [
        ("compliance_rag.retrieval", "leg finished"),
        ("anthropic._base_client", "retrying request"),
    ]


def test_uvicorn_loggers_go_through_the_json_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    # uvicorn's default config gives its loggers their own plain-text handlers with propagate=False
    import logging

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [logging.StreamHandler()]
        lg.propagate = False
    configure_logging("INFO", service="api")
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    out = capsys.readouterr()
    line = json.loads((out.out + out.err).strip().splitlines()[-1])
    assert line["event"] == "Application startup complete." and line["service"] == "api"


def _raise_chained() -> None:
    try:
        raise ValueError("CAUSE-SECRET Complaint files under a litigation hold")
    except ValueError as cause:
        raise RuntimeError("SECRET-TEXT-123 Failing row contains (Legal-only chunk text)") from cause


def test_exception_messages_never_reach_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    # tracebacks keep their type and frames; messages (psycopg row details, pydantic input values, document
    # text) are dropped, also where a library interpolates the exception into its own message (arq)
    import logging

    configure_logging("INFO", service="api")
    try:
        _raise_chained()
    except RuntimeError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=exc)
        logging.getLogger("arq.worker").exception(
            "%6.2fs ! %s failed, %s: %s", 0.1, "job", type(exc).__name__, exc
        )
        structlog.get_logger("compliance_rag.api").exception("unhandled")
    out = capsys.readouterr()
    raw = out.out + out.err
    assert "SECRET" not in raw and "litigation" not in raw and "Legal-only" not in raw
    events = [json.loads(line) for line in raw.strip().splitlines()]
    assert len(events) == 3
    for event in events:
        assert "RuntimeError" in event["exception"] and "ValueError" in event["exception"]
        assert "_raise_chained" in event["exception"]  # the frames are kept
    assert events[1]["event"].startswith("  0.10s ! job failed, RuntimeError: ")


def test_error_labels_name_the_type_and_sqlstate_never_the_message() -> None:
    import psycopg

    from compliance_rag.obs.logging import error_label

    assert error_label(RuntimeError("Failing row contains (Legal-only chunk text)")) == "RuntimeError"
    check = psycopg.errors.CheckViolation(
        "new row violates check constraint; DETAIL: Failing row contains (...)"
    )
    assert error_label(check) == "CheckViolation (SQLSTATE 23514)"


def test_a_traceback_logged_as_text_keeps_types_and_frames_only(capsys: pytest.CaptureFixture[str]) -> None:
    # uvicorn logs a failed lifespan as `logger.error(traceback.format_exc())`: no exc_info, the text is the message
    import logging
    import traceback

    configure_logging("INFO", service="api")
    try:
        _raise_chained()
    except RuntimeError:
        logging.getLogger("uvicorn.error").error(
            traceback.format_exc() + "DETAIL:  Key (v)=(Legal-only) already exists."
        )
    out = capsys.readouterr()
    raw = out.out + out.err
    assert "SECRET" not in raw and "litigation" not in raw and "Legal-only" not in raw
    event = json.loads(raw.strip().splitlines()[-1])["event"]
    assert "Traceback (most recent call last):" in event and "_raise_chained" in event
    assert "RuntimeError" in event and "ValueError" in event


def test_message_continuations_and_notes_of_a_text_traceback_are_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # every line after an exception-type line belongs to its message or notes until the next traceback header
    import logging
    import traceback

    configure_logging("INFO", service="api")
    try:
        try:
            error = ValueError("first line\nLitigationHold\nSecret: hunter2\nAcme.Corp")
            error.add_note("ConfidentialSettlement")
            error.add_note("token: abc")
            raise error
        except ValueError as cause:
            raise RuntimeError("Outer\nPrivilegedMemo") from cause
    except RuntimeError:
        logging.getLogger("uvicorn.error").error(traceback.format_exc())
    out = capsys.readouterr()
    event = json.loads((out.out + out.err).strip().splitlines()[-1])["event"]
    for leaked in (
        "LitigationHold",
        "Secret",
        "hunter2",
        "Acme.Corp",
        "ConfidentialSettlement",
        "token",
        "Outer",
        "PrivilegedMemo",
        "first line",
    ):
        assert leaked not in event, leaked
    assert "ValueError" in event and "RuntimeError" in event and "direct cause" in event


def test_exception_groups_logged_as_text_keep_their_frames_and_types(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging
    import traceback

    configure_logging("INFO", service="api")
    try:
        raise ExceptionGroup("GroupSecret", [KeyError("KeySecret"), OSError("OsSecret")])
    except ExceptionGroup:
        logging.getLogger("uvicorn.error").error(traceback.format_exc())
    out = capsys.readouterr()
    event = json.loads((out.out + out.err).strip().splitlines()[-1])["event"]
    assert "Secret" not in event
    assert "ExceptionGroup" in event and "KeyError" in event and "OSError" in event and 'File "' in event


def _text_traceback_event(capsys: pytest.CaptureFixture[str], exc: BaseException) -> str:
    import logging
    import traceback

    configure_logging("INFO", service="api")
    try:
        raise exc
    except BaseException:
        logging.getLogger("uvicorn.error").error(traceback.format_exc())
    out = capsys.readouterr()
    return str(json.loads((out.out + out.err).strip().splitlines()[-1])["event"])


@pytest.mark.parametrize(
    "message",
    [
        "Traceback (most recent call last): hunter2",
        "x\nDuring handling of the above exception secret=hunter2",
        "x\nThe above exception was the direct cause of the following exception:\nLitigationHold",
        'x\n+-----+\n  File "a", line 2, in hunter2',
        'x\nTraceback (most recent call last):\n  File "hunter2", line 1, in f\nLitigationHold: y',
    ],
)
def test_crafted_messages_cannot_pass_as_traceback_structure(
    capsys: pytest.CaptureFixture[str], message: str
) -> None:
    event = _text_traceback_event(capsys, ValueError(message))
    assert "hunter2" not in event and "LitigationHold" not in event and "secret" not in event
    assert "ValueError" in event


def test_unusual_exception_names_do_not_open_a_gap(capsys: pytest.CaptureFixture[str]) -> None:
    class Ärger(Exception):  # a non-ASCII class name defined in a function (<locals>)
        pass

    event = _text_traceback_event(capsys, Ärger("first\nLitigationHold"))
    assert "LitigationHold" not in event and "first" not in event and "Ärger" in event


def test_traceback_text_without_an_exception_in_context_is_withheld(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging

    configure_logging("INFO", service="api")
    text = 'Traceback (most recent call last):\n  File "x.py", line 1, in f\nValueError: LitigationHold'
    logging.getLogger("uvicorn.error").error(text)  # no active exception: nothing to render it from
    out = capsys.readouterr()
    event = json.loads((out.out + out.err).strip().splitlines()[-1])["event"]
    assert "LitigationHold" not in event and "withheld" in event


def test_a_message_holding_the_traceback_marker_is_masked_before_the_text_is_cut(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # arq logs "%6.2fs ! %s failed, %s: %s" with exc_info: the message precedes any marker it contains
    import logging

    configure_logging("INFO", service="worker")
    error = RuntimeError(
        "Failing row contains (LegalOnly: see Traceback (most recent call last): in the runbook)"
    )
    try:
        raise error
    except RuntimeError as exc:
        logging.getLogger("arq.worker").exception(
            "%6.2fs ! %s failed, %s: %s", 0.1, "job", type(exc).__name__, exc
        )
    logging.getLogger("arq.worker").error("failed: %s", error, exc_info=error)  # outside the except block
    out = capsys.readouterr()
    lines = (out.out + out.err).strip().splitlines()
    for line in lines[-2:]:
        event = json.loads(line)
        assert "LegalOnly" not in event["event"] and "Failing row" not in event["event"]
        assert "withheld" not in event["event"] and "RuntimeError" in event["exception"]


def test_wide_exception_groups_are_capped(capsys: pytest.CaptureFixture[str]) -> None:
    def nest(depth: int) -> BaseException:
        if depth == 0:
            return KeyError("leaf")
        return ExceptionGroup("g", [nest(depth - 1) for _ in range(20)])

    event = _text_traceback_event(capsys, nest(3))
    assert "more exceptions" in event and len(event) < 200_000


def test_an_exception_whose_str_fails_is_still_rendered(capsys: pytest.CaptureFixture[str]) -> None:
    class Broken(Exception):
        def __str__(self) -> str:
            raise RuntimeError("LitigationHold")

    event = _text_traceback_event(capsys, Broken())
    assert "LitigationHold" not in event and "Broken" in event


def test_plain_messages_inside_an_except_block_are_not_masked_by_the_active_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging

    configure_logging("INFO", service="api")
    try:
        raise ValueError("e")
    except ValueError:
        logging.getLogger("compliance_rag.test").warning("retrying the request")
    out = capsys.readouterr()
    assert json.loads((out.out + out.err).strip().splitlines()[-1])["event"] == "retrying the request"


@pytest.mark.parametrize("message", ["recent", "e", "most", "call"])
def test_a_message_inside_the_traceback_header_cannot_stop_the_substitution(
    capsys: pytest.CaptureFixture[str], message: str
) -> None:
    error = ValueError(message)
    error.add_note("NoteSecret LitigationHold")
    event = _text_traceback_event(capsys, error)
    assert "NoteSecret" not in event and "raise exc" not in event  # notes and source lines never pass
    assert event.startswith("Traceback (most recent call last):\n") and "ValueError" in event


def test_a_short_exc_info_message_cannot_stop_the_substitution(capsys: pytest.CaptureFixture[str]) -> None:
    import logging
    import traceback

    configure_logging("INFO", service="api")
    try:
        error = ValueError("e")
        error.add_note("NoteSecret")
        raise error
    except ValueError as exc:
        logging.getLogger("uvicorn.error").error("startup: " + traceback.format_exc(), exc_info=exc)
    out = capsys.readouterr()
    event = json.loads((out.out + out.err).strip().splitlines()[-1])["event"]
    assert "NoteSecret" not in event and "raise error" not in event
    assert event.startswith("startup: Traceback (most recent call last):\n")


def test_deeply_nested_exception_groups_render_a_bounded_number_of_members(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def nest(depth: int) -> BaseException:
        return KeyError("leaf") if depth == 0 else ExceptionGroup("g", [nest(depth - 1) for _ in range(6)])

    event = _text_traceback_event(capsys, nest(5))  # 6**5 leaves within the depth and width caps
    assert event.count("KeyError") <= 100 and "more exceptions" in event and len(event) < 100_000


@pytest.mark.parametrize(
    "message", ["Traceback (most recent call last):", 'Traceback (most recent call last):\n  File "']
)
def test_a_message_equal_to_the_start_of_the_traceback_cannot_hide_it(
    capsys: pytest.CaptureFixture[str], message: str
) -> None:
    error = ValueError(message)
    error.add_note("NoteSecret")
    event = _text_traceback_event(capsys, error)
    assert "NoteSecret" not in event and "raise exc" not in event and "ValueError" in event
