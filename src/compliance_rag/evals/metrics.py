"""Metrics for BUILD.md §11. Gold spans match on (document_id, version) plus the normalised span text."""

from __future__ import annotations

import re
from typing import Any

from compliance_rag.auth.personas import persona_principal
from compliance_rag.graph.verify import normalize

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm_values(text: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUM.findall(text)}


def gold_hit(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    return (
        candidate["document_id"] == gold["document_id"]
        and int(candidate["version"]) == int(gold["version"])
        and normalize(gold["span"]) in normalize(candidate["text"])
    )


def recall_at_10(row: dict[str, Any], output: dict[str, Any]) -> float | None:
    golds = row["meta"].get("gold") or []
    if row["expected"]["abstain"] or not golds:
        return None
    top = output.get("retrieved", [])[:10]
    return sum(any(gold_hit(c, g) for c in top) for g in golds) / len(golds)


def mrr_at_10(row: dict[str, Any], output: dict[str, Any]) -> float | None:
    golds = row["meta"].get("gold") or []
    if row["expected"]["abstain"] or not golds:
        return None
    for rank, c in enumerate(output.get("retrieved", [])[:10], start=1):
        if any(gold_hit(c, g) for g in golds):
            return 1.0 / rank
    return 0.0


def key_fact(row: dict[str, Any], output: dict[str, Any]) -> float | None:
    """``contains_all`` on normalised values (thousands separators stripped)."""
    if row["expected"]["abstain"]:
        return None
    if output.get("abstained"):
        return 0.0
    found = norm_values(output.get("answer", ""))
    return 1.0 if set(row["expected"]["values"]) <= found else 0.0


def abstention_correct(row: dict[str, Any], output: dict[str, Any]) -> float:
    return 1.0 if bool(output.get("abstained")) == bool(row["expected"]["abstain"]) else 0.0


def _output_text(output: dict[str, Any]) -> str:
    parts = [output.get("answer") or "", output.get("message") or ""]
    for claim in output.get("claims", []):
        parts.append(claim["text"])
        parts += [c["quote"] + " " + c["document_id"] for c in claim["citations"]]
    parts += [v["document_id"] for v in output.get("versions", [])]
    return "\n".join(parts)


def acl_leak(row: dict[str, Any], output: dict[str, Any]) -> float:
    """1.0 when any output or retrieved chunk exposes something the persona may not read."""
    groups = set(persona_principal(row["input"].get("persona", "analyst"))["groups"])
    for c in output.get("retrieved", []):
        if not set(c.get("acl_groups", [])) & groups:
            return 1.0
    meta = row["meta"]
    restricted = meta.get("restricted_document")
    if restricted:
        text = _output_text(output)
        if restricted in text or restricted in {c["document_id"] for c in output.get("retrieved", [])}:
            return 1.0
        if normalize(meta.get("restricted_span", "")) and normalize(meta["restricted_span"]) in normalize(
            text
        ):
            return 1.0
    return 0.0


def stale_citations(row: dict[str, Any], output: dict[str, Any]) -> tuple[int, int]:
    """(stale, total) cited versions whose validity window excludes ``as_of``."""
    as_of = row["input"]["as_of"]
    total = stale = 0
    for v in output.get("versions", []):
        total += 1
        if not (v["valid_from"] <= as_of and (v["valid_to"] is None or as_of < v["valid_to"])):
            stale += 1
    return stale, total


def citation_precision(output: dict[str, Any]) -> tuple[int, int]:
    """(good, total) citations whose quote holds every value stated in its claim."""
    good = total = 0
    for claim in output.get("claims", []):
        values = norm_values(claim["text"])
        for cit in claim["citations"]:
            total += 1
            if values <= norm_values(cit["quote"]):
                good += 1
    return good, total


def hallucinated_citations(output: dict[str, Any], chunk_texts: dict[str, str]) -> tuple[int, int]:
    """(bad, total) citations whose quote is not in the re-fetched chunk text."""
    bad = total = 0
    for claim in output.get("claims", []):
        for cit in claim["citations"]:
            total += 1
            text = chunk_texts.get(cit["chunk_id"])
            if text is None or normalize(cit["quote"]) not in normalize(text):
                bad += 1
    return bad, total
