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
