"""Eval questions and judge labels by construction (T-14)."""

import json
from collections import Counter
from pathlib import Path

from data.generator.corpus import SEED, build_corpus
from data.generator.questions import PERSONA_GROUPS, build_judge_labels, build_questions

ROOT = Path(__file__).resolve().parents[3]
QUESTIONS = ROOT / "evals" / "datasets" / "questions.v1.jsonl"
LABELS = ROOT / "evals" / "datasets" / "judge_labels.v1.jsonl"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_partition_counts() -> None:
    rows = _rows(QUESTIONS)
    assert len(rows) == 300
    assert Counter(r["split"] for r in rows) == {"dev": 180, "test": 120}
    cats = Counter(r["meta"]["category"] for r in rows)
    assert cats == {
        "single_hop": 120,
        "multi_hop": 40,
        "numeric": 40,
        "must_abstain": 50,
        "acl_probe": 30,
        "version_sensitive": 20,
    }
    answerable = [r for r in rows if not r["expected"]["abstain"]]
    assert len(answerable) == 220  # 200 answerable + 20 version-sensitive
    assert len({r["id"] for r in rows}) == 300
    assert len(_rows(LABELS)) == 80


def test_committed_datasets_match_generator() -> None:
    policies = build_corpus(SEED)
    assert build_questions(policies) == _rows(QUESTIONS)
    assert build_judge_labels(policies) == _rows(LABELS)


def test_gold_spans_exist_in_gold_versions_and_personas_authorized() -> None:
    by_id = {p.document_id: p for p in build_corpus(SEED)}
    for row in _rows(QUESTIONS):
        persona_groups = set(PERSONA_GROUPS[row["input"]["persona"]])
        for gold in row["meta"]["gold"]:
            policy = by_id[gold["document_id"]]
            version = policy.versions[gold["version"] - 1]
            assert any(f.statement == gold["span"] for f in version.facts)
            assert version.valid_from <= row["input"]["as_of"]
            assert version.valid_to is None or row["input"]["as_of"] < version.valid_to
            authorized = bool(persona_groups & set(policy.acl_groups))
            if row["meta"]["category"] == "acl_probe":
                assert not authorized
            else:
                assert authorized


def test_no_question_text_shared_between_splits() -> None:
    rows = _rows(QUESTIONS)
    dev = {r["input"]["question"] for r in rows if r["split"] == "dev"}
    test = {r["input"]["question"] for r in rows if r["split"] == "test"}
    assert not dev & test


def test_journey_question_present() -> None:
    rows = _rows(QUESTIONS)
    journey = [
        r for r in rows if r["input"]["question"] == "What is the maximum age of a proof-of-address document?"
    ]
    assert journey and journey[0]["expected"]["values"] == ["90"]
