"""Local LSA embedder (FR-4, T-16)."""

import numpy as np
import pytest

from compliance_rag.embed import EmbedderMismatch, create_embedder
from compliance_rag.embed.lsa import LocalLSAEmbedder
from data.generator.corpus import SEED, build_corpus


@pytest.fixture(scope="module")
def texts() -> list[str]:
    out = []
    for policy in build_corpus(SEED)[:60]:
        for article in policy.current.articles:
            out.append(article.heading + "\n" + "\n".join(article.paragraphs))
    return out


def test_fit_is_deterministic(texts: list[str]) -> None:
    a = LocalLSAEmbedder(dim=384, seed=2026).fit(texts)
    b = LocalLSAEmbedder(dim=384, seed=2026).fit(texts)
    va, vb = a.embed_documents(texts[:50]), b.embed_documents(texts[:50])
    assert va.shape == (50, 384)
    assert np.max(np.abs(va - vb)) < 1e-6
    assert a.fingerprint() == b.fingerprint()


def test_vectors_are_unit_norm_and_query_matches_document(texts: list[str]) -> None:
    emb = LocalLSAEmbedder(dim=384, seed=2026).fit(texts)
    vecs = emb.embed_documents(texts[:20])
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
    q = emb.embed_query(texts[3])
    assert int(np.argmax(vecs @ q)) == 3


def test_save_load_round_trip(texts: list[str]) -> None:
    emb = LocalLSAEmbedder(dim=384, seed=2026).fit(texts)
    blob = emb.to_bytes()
    loaded = LocalLSAEmbedder.from_bytes(blob)
    assert loaded.fingerprint() == emb.fingerprint()
    assert np.max(np.abs(loaded.embed_documents(texts[:5]) - emb.embed_documents(texts[:5]))) < 1e-6
    assert b"pickle" not in blob[:100]


def test_small_corpus_pads_to_dim() -> None:
    emb = LocalLSAEmbedder(dim=384, seed=2026).fit(["alpha beta", "beta gamma", "gamma delta"])
    assert emb.embed_query("alpha").shape == (384,)


def test_unfitted_raises() -> None:
    with pytest.raises(RuntimeError):
        LocalLSAEmbedder().embed_query("x")


def test_factory_checks_index_meta() -> None:
    emb = create_embedder("lsa", dim=384)
    with pytest.raises(EmbedderMismatch):
        emb.check_compatible({"name": "titan", "dim": 512, "fingerprint": "x"})
