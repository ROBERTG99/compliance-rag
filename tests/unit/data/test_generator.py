"""Seeded corpus generator (T-12)."""

from collections import Counter

from data.generator.corpus import SEED, build_corpus, corpus_fingerprint


def test_seed_2026_is_reproducible() -> None:
    a = build_corpus(SEED)
    b = build_corpus(SEED)
    assert corpus_fingerprint(a) == corpus_fingerprint(b)
    assert corpus_fingerprint(build_corpus(SEED + 1)) != corpus_fingerprint(a)


def test_corpus_shape() -> None:
    policies = build_corpus(SEED)
    assert len(policies) == 400
    n_versions = sum(len(p.versions) for p in policies)
    assert 1100 <= n_versions <= 1300
    assert all(2 <= len(p.versions) <= 4 for p in policies)
    domains = Counter(p.domain for p in policies)
    assert set(domains) == {"kyc", "aml", "limits", "retention", "complaints", "vendors"}
    ids = [p.document_id for p in policies]
    assert len(set(ids)) == len(ids)


def test_versions_are_contiguous_and_one_open() -> None:
    for p in build_corpus(SEED):
        assert p.versions[-1].valid_to is None
        for prev, nxt in zip(p.versions, p.versions[1:], strict=False):
            assert prev.valid_to == nxt.valid_from
            assert prev.valid_from < nxt.valid_from


def test_product_fact_pairs_are_unique() -> None:
    seen: set[tuple[str, str]] = set()
    for p in build_corpus(SEED):
        keys = {f.key for f in p.current.facts}
        for key in keys:
            pair = (p.product or p.document_id, key)
            assert pair not in seen, pair
            seen.add(pair)


def test_anchor_documents() -> None:
    by_id = {p.document_id: p for p in build_corpus(SEED)}
    kyc = by_id["KYC-0042"]
    assert [v.version for v in kyc.versions] == [1, 2, 3]
    assert kyc.versions[2].valid_from == "2026-03-01"
    assert kyc.version_at("2025-12-31").version == 2
    assert by_id["CMP-0215"].acl_groups == ["legal"]
    assert len(by_id["AML-0107"].versions) == 3
