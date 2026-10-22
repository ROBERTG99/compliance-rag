"""Red-team cases: generated from the corpus, committed file equals the generator output."""

from __future__ import annotations

from pathlib import Path

from data.generator.corpus import build_corpus
from data.generator.injections import N_INJECTED
from data.generator.redteam import build_redteam_cases, dump_cases, reader_for

ROOT = Path(__file__).resolve().parents[3]


def test_committed_cases_equal_the_generator_output() -> None:
    cases = build_redteam_cases(build_corpus(2026))
    assert (ROOT / "evals/redteam/cases.v1.yaml").read_text(encoding="utf-8") == dump_cases(cases)
    documents = [c for c in cases if c["metadata"]["kind"] == "document"]
    assert len(documents) == N_INJECTED
    assert len(cases) - len(documents) >= 10
    assert all(c["vars"]["persona"] in {"analyst", "legal", "support", "admin"} for c in cases)


def test_document_cases_ask_as_a_persona_allowed_to_read_the_policy() -> None:
    assert reader_for(["all"]) == "support"
    assert reader_for(["compliance"]) == "analyst"
    assert reader_for(["legal"]) == "legal"


def test_guard_keeps_every_injected_fact_and_removes_every_injection() -> None:
    """A red-team miss can never be the guard deleting the fact next to an injection."""
    from compliance_rag.guard.context_guard import guard_text

    for policy in build_corpus(2026):
        injection = policy.current.injection
        if not injection:
            continue
        fact = next(f for f in policy.current.facts if f.key == injection["fact"])
        article = "\n\n".join(policy.current.articles[fact.article - 1].paragraphs)
        guarded = guard_text(article)
        assert fact.statement in guarded.text, policy.document_id
        assert injection["canary"] not in guarded.text, policy.document_id
