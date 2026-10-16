"""Test-split registry used by feedback triage (FR-12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from compliance_rag.evals.splits import SplitRegistryUnavailable, in_test_split, question_key


def _write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    (tmp_path / "questions.v1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def test_normalised_test_question_is_detected(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        [
            {"split": "test", "input": {"question": "What is the  EDD threshold?"}},
            {"split": "dev", "input": {"question": "Who owns KYC-0042?"}},
        ],
    )
    assert in_test_split("what is the edd threshold?\n", root)
    assert in_test_split("ＷＨＡＴ is the EDD threshold?", root)  # NFKC full-width
    assert not in_test_split("Who owns KYC-0042?", root)
    assert question_key("a  b") == question_key(" A b ")


def test_missing_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SplitRegistryUnavailable):
        in_test_split("anything", tmp_path / "nowhere")
