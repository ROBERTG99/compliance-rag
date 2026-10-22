"""Eval metrics, graded against ground truth from the corpus model."""

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


def _answerable(golds: list[dict[str, Any]], values: list[str]) -> dict[str, Any]:
    return {
        "input": {"question": "q", "as_of": "2026-10-16", "persona": "analyst"},
        "expected": {"abstain": False, "values": values},
        "meta": {"category": "multi_hop", "gold": golds},
    }


GOLD_A = {"document_id": "KYC-0042", "version": 3, "span": "must not be older than 90 days"}
GOLD_B = {"document_id": "AML-0107", "version": 3, "span": "reviewed every 18 months"}


def _chunk(doc: str, version: int, text: str) -> dict[str, Any]:
    return {"document_id": doc, "version": version, "text": text}


def test_recall_counts_each_gold_span_and_needs_the_right_version() -> None:
    from compliance_rag.evals.metrics import recall_at_10

    row = _answerable([GOLD_A, GOLD_B], ["90", "18"])
    hit_a = _chunk("KYC-0042", 3, "A proof of address must not be older than  90 days.")
    wrong_version = _chunk("AML-0107", 2, "Relationships are reviewed every 18 months.")
    assert recall_at_10(row, {"retrieved": [hit_a, wrong_version]}) == 0.5
    assert recall_at_10({**row, "expected": {"abstain": True, "values": []}}, {"retrieved": [hit_a]}) is None


def test_mrr_is_zero_when_the_first_hit_is_past_rank_ten() -> None:
    from compliance_rag.evals.metrics import mrr_at_10

    row = _answerable([GOLD_A], ["90"])
    filler = [_chunk("LIM-0001", 1, "unrelated")] * 10
    hit = _chunk("KYC-0042", 3, "must not be older than 90 days")
    assert mrr_at_10(row, {"retrieved": [*filler, hit]}) == 0.0
    assert mrr_at_10(row, {"retrieved": [filler[0], hit]}) == 0.5


def test_key_fact_and_abstention() -> None:
    from compliance_rag.evals.metrics import abstention_correct, key_fact

    row = _answerable([GOLD_A], ["10000"])
    assert key_fact(row, {"abstained": False, "answer": "The limit is EUR 10,000."}) == 1.0
    assert key_fact(row, {"abstained": True, "answer": ""}) == 0.0  # abstaining on an answerable question
    probe = {**_row("support"), "expected": {"abstain": True, "values": []}}
    assert abstention_correct(probe, {"abstained": True}) == 1.0  # ACL probes count as must-abstain
    assert abstention_correct(row, {"abstained": True}) == 0.0


def test_a_version_unknown_to_the_corpus_counts_as_stale() -> None:
    row = _row("analyst")
    output = {
        "versions": [{"document_id": "KYC-0042", "version": 9, "valid_from": "2026-01-01", "valid_to": None}]
    }
    assert stale_citations(row, output, TRUTH) == (1, 1)


def test_a_ratio_with_nothing_to_count_has_no_value() -> None:
    from evalgate.runner import aggregate
    from evalgate.suite import MetricSpec

    spec = MetricSpec(name="hallucinated", fn="m:f", aggregate="ratio")
    assert aggregate(spec, [(0, 0), (0, 0)]) == (None, 0)
