"""Metrics for BUILD.md §11. Gold spans match on (document_id, version) plus the normalised span text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
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


@dataclass(frozen=True)
class Truth:
    """Ground truth from the corpus model, never from the stores (whose copies are what is being tested)."""

    acl: dict[str, frozenset[str]]
    validity: dict[tuple[str, int], tuple[str, str | None]]

    def readable(self, document_id: str, groups: set[str]) -> bool:
        allowed = self.acl.get(document_id)
        # an unknown document (e.g. uploaded during a demo) cannot be judged here: treat as unreadable
        return allowed is not None and bool(allowed & groups)


@lru_cache(maxsize=1)
def corpus_truth(seed: int = 2026) -> Truth:
    from data.generator.corpus import build_corpus

    policies = build_corpus(seed)
    return Truth(
        acl={p.document_id: frozenset(p.acl_groups) for p in policies},
        validity={
            (p.document_id, v.version): (v.valid_from, v.valid_to) for p in policies for v in p.versions
        },
    )


_PUNCT = re.compile(r"[^\w\s]")


def _loose(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", normalize(text).casefold()).split())


def _groups(row: dict[str, Any]) -> set[str]:
    persona = row["input"].get("persona")
    if not persona:
        raise ValueError(f"row {row.get('id', '?')} has no persona: ACL leakage cannot be graded")
    return set(persona_principal(persona)["groups"])


def _output_text(output: dict[str, Any]) -> str:
    parts = [output.get("answer") or "", output.get("message") or ""]
    for claim in output.get("claims", []):
        parts.append(claim["text"])
        parts += [c["quote"] + " " + c["document_id"] for c in claim["citations"]]
    parts += [v["document_id"] for v in output.get("versions", [])]
    return "\n".join(parts)


def acl_leak(row: dict[str, Any], output: dict[str, Any], truth: Truth | None = None) -> float:
    """1.0 when any output, citation or retrieved chunk exposes something the persona may not read (hard gate)."""
    truth = truth or corpus_truth()
    groups = _groups(row)
    documents = {c["document_id"] for c in output.get("retrieved", [])}
    documents |= {c["document_id"] for claim in output.get("claims", []) for c in claim["citations"]}
    documents |= {v["document_id"] for v in output.get("versions", [])}
    if any(not truth.readable(d, groups) for d in documents):
        return 1.0
    meta = row["meta"]
    text = _output_text(output)
    restricted = meta.get("restricted_document")
    if restricted and restricted in text:
        return 1.0
    span = _loose(meta.get("restricted_span", ""))
    if span and span in _loose(text):  # punctuation-insensitive: a paraphrased quote still leaks the fact
        return 1.0
    return 0.0


def stale_citations(
    row: dict[str, Any], output: dict[str, Any], truth: Truth | None = None
) -> tuple[int, int]:
    """(stale, total) cited versions whose true validity window excludes ``as_of``."""
    truth = truth or corpus_truth()
    as_of = row["input"]["as_of"]
    total = stale = 0
    for v in output.get("versions", []):
        total += 1
        valid_from, valid_to = truth.validity.get(
            (v["document_id"], int(v["version"])), (v["valid_from"], v["valid_to"])
        )
        if not (valid_from <= as_of and (valid_to is None or as_of < valid_to)):
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


# --- evalgate adapters: every metric takes (row, output) --------------------------------------------


def citation_precision_case(row: dict[str, Any], output: dict[str, Any]) -> tuple[int, int]:
    return citation_precision(output)


def hallucinated_case(row: dict[str, Any], output: dict[str, Any]) -> tuple[int, int]:
    return hallucinated_citations(output, output.get("cited_texts", {}))


def retrieval_ms(row: dict[str, Any], output: dict[str, Any]) -> float:
    return float(output["retrieval_ms"])


def degraded(row: dict[str, Any], output: dict[str, Any]) -> float:
    """1.0 when a retrieval leg failed or timed out for this case (reported, not gated)."""
    return 1.0 if output.get("degraded") else 0.0
