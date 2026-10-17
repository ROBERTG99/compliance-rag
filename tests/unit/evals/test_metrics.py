"""Eval metrics, graded against ground truth from the corpus model (BUILD.md §11)."""

from __future__ import annotations

from typing import Any

import pytest

from compliance_rag.evals.metrics import (
    Truth,
    acl_leak,
    citation_precision,
    hallucinated_citations,
    stale_citations,
)

TRUTH = Truth(
    acl={"CMP-0215": frozenset({"legal"}), "KYC-0042": frozenset({"all"})},
    validity={("KYC-0042", 2): ("2025-01-01", "2026-03-01"), ("KYC-0042", 3): ("2026-03-01", None)},
)


def _row(persona: str | None = "support", **meta: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "input": {"question": "q", "as_of": "2026-10-16"},
        "meta": {"category": "acl_probe", **meta},
    }
    if persona:
        row["input"]["persona"] = persona
    return row


def _retrieved(doc: str, groups: list[str]) -> dict[str, Any]:
    return {"chunk_id": "x", "document_id": doc, "version": 1, "acl_groups": groups, "text": "t"}


def test_acl_leak_metric_detects_leak() -> None:
    clean: dict[str, Any] = {
        "abstained": True,
        "message": "I can't answer that.",
        "claims": [],
        "versions": [],
        "retrieved": [],
    }
    assert acl_leak(_row(), clean, TRUTH) == 0.0
    # a retrieved chunk the persona may not read, even if the index copy claims "all" (stale ACL)
    stale_copy = {**clean, "retrieved": [_retrieved("CMP-0215", ["all"])]}
    assert acl_leak(_row(), stale_copy, TRUTH) == 1.0
    # the restricted id or span in any output text
    named = {**clean, "message": "See CMP-0215."}
    assert acl_leak(_row(restricted_document="CMP-0215"), named, TRUTH) == 1.0
    span = "Files under a litigation hold are kept for 7 years after the hold is lifted."
    quoted = {
        **clean,
        "answer": "files under a litigation hold are kept for 7 years after the hold is lifted",
    }
    assert acl_leak(_row(restricted_span=span), quoted, TRUTH) == 1.0
    # a citation to a restricted document
    cited = {
        **clean,
        "claims": [
            {
                "text": "x",
                "citations": [{"document_id": "CMP-0215", "version": 2, "quote": "q", "chunk_id": "c"}],
            }
        ],
    }
    assert acl_leak(_row(), cited, TRUTH) == 1.0
    # the authorised persona is fine
    assert acl_leak(_row(persona="legal"), stale_copy, TRUTH) == 0.0


def test_acl_leak_requires_a_persona() -> None:
    with pytest.raises(ValueError, match="persona"):
        acl_leak(_row(persona=None), {"retrieved": []}, TRUTH)


def test_stale_citations_use_true_validity_windows() -> None:
    row = _row(persona="analyst")
    out = {
        "versions": [{"document_id": "KYC-0042", "version": 2, "valid_from": "2025-01-01", "valid_to": None}]
    }
    # the response claims v2 is open-ended; the truth says it ended on 2026-03-01
    assert stale_citations(row, out, TRUTH) == (1, 1)
    ok = {
        "versions": [{"document_id": "KYC-0042", "version": 3, "valid_from": "2026-03-01", "valid_to": None}]
    }
    assert stale_citations(row, ok, TRUTH) == (0, 1)


def test_citation_precision_and_hallucination() -> None:
    out = {
        "claims": [
            {
                "text": "Proof of address must be at most 90 days old.",
                "citations": [
                    {
                        "chunk_id": "a",
                        "quote": "not be older than 90 days",
                        "document_id": "KYC-0042",
                        "version": 3,
                    },
                    {
                        "chunk_id": "b",
                        "quote": "not be older than 120 days",
                        "document_id": "KYC-0042",
                        "version": 2,
                    },
                ],
            }
        ]
    }
    assert citation_precision(out) == (1, 2)
    assert hallucinated_citations(
        out, {"a": "It must not be older than 90 days.", "b": "something else"}
    ) == (1, 2)


def test_degraded_marks_cases_where_a_leg_failed() -> None:
    from compliance_rag.evals.metrics import degraded

    assert degraded({}, {"degraded": ["bm25"]}) == 1.0
    assert degraded({}, {"degraded": []}) == 0.0
