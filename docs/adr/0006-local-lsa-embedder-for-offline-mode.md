# 0006. Local LSA embedder for offline mode

## Status

Accepted

## Date

2026-10-16

## Context

The build and the tests must run with no API keys and no public network (NFR-9, socket guard in
`tests/conftest.py`), yet retrieval needs a dense leg and the evals must be reproducible byte for byte.
Hosted embedding models (Titan, OpenAI) are supported adapters but cannot be the default: they need
credentials and network, and their vectors can change between provider versions.

## Decision

`LocalLSAEmbedder` is the default (`CRAG_EMBEDDER=lsa`, `src/compliance_rag/settings.py:56`): TF-IDF over
unigrams and bigrams (English stop words, sublinear TF, at most 60,000 features) followed by
`TruncatedSVD` to 384 dimensions with seed 2026 (`src/compliance_rag/embed/lsa.py:18-26`, `lsa.py:47`).
Output vectors are L2-normalised (`lsa.py:65`). The fitted model is serialised as `.npz` (vocabulary, IDF,
components), never pickle (`lsa.py:67-94`), stored in the object store and recorded in `index_meta`.
At start-up the configured embedder must match the index metadata or `EmbedderMismatch` is raised
(`src/compliance_rag/embed/registry.py:48-58`). The fingerprint of the fitted model is part of every eval
report (`evals/REPORT.md`, `embedder: lsa-384-...`). `TitanEmbedder` and `OpenAIEmbedder` implement the
same interface and are tested against recorded fixtures only.

## Alternatives considered

- **A downloaded sentence-embedding model (sentence-transformers).** Rejected as the default: the weights
  would be fetched at runtime or vendored, which breaks the offline-first rule; the spec lists
  scikit-learn as the deterministic offline choice and sentence-transformers as the alternative rejected
  (`docs/specs/000-build-spec.md` §5 tech stack table).
- **Hosted embeddings (Titan, OpenAI) as the default.** Rejected: they need keys and network. They stay
  available behind the interface; their fixtures are synthetic until `make record-fixtures` is run with
  keys (`docs/KNOWN_LIMITATIONS.md`, Providers row).
- **Hash or bag-of-words vectors.** Rejected: no semantic generalisation beyond the lexical leg, so the
  vector leg would add little.

## Consequences

Positive:

- Deterministic and offline: fitting twice on the same corpus gives matching vectors
  (`tests/unit/embed/test_lsa_embedder.py::test_fit_is_deterministic`), so eval numbers are reproducible.
- No data leaves the machine, and no cost or latency from a provider.

Negative:

- LSA is a corpus-specific representation built from term co-occurrence; it is expected to generalise
  less well on paraphrase than a neural embedding, but that is not measured here. In the ablation the vector leg alone has recall@10 0.756 and mrr@10 0.681 against 0.812 and 0.825 for
  BM25 alone (`evals/REPORT.md` "Retrieval ablation"). The repo has not measured a neural embedder, so
  how much is lost against one is unknown.
- The model is fitted on the corpus: vocabulary introduced by later documents is unknown to it until it
  is refitted, which `crag reindex --reembed` does in seed order (`docs/DECISIONS.md`, 2026-10-17 row on
  `crag reindex`). A query with no term in the fitted vocabulary embeds to a zero vector, which skips
  the vector leg for that query (`src/compliance_rag/retrieval/hybrid.py:103-105`).
- The reranker, whose features include cosine, is fitted on top of LSA vectors; switching embedder
  requires refitting it on the dev split (`scripts/fit_reranker.py`,
  `src/compliance_rag/rerank/feature.py:1-6`).
- These retrieval numbers are not a statement about production quality with a hosted embedder; they
  describe the offline default.
