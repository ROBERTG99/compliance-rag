# 0005. Verified extractive citations over free-form citations

## Status

Accepted

## Date

2026-10-16

## Context

An answer about a policy is only useful if the reader can check it against the exact text of the version
in force. A model that is allowed to cite loosely can invent a reference, quote text that is not in the
document, or state a number that the quoted source does not contain. The model only composes; checking
is deterministic code (`CLAUDE.md`). Documents also have versions, so a citation must name the
`(document_id, version)` and the character span, not just a title.

## Decision

The model returns structured claims, each with citations of the form `{chunk_id, quote}`. A claim
survives only if, for every citation (`src/compliance_rag/graph/verify.py:87-118`):

1. the chunk is in the context given to the model (`chunk_not_in_context`);
2. the quote is an exact substring of that chunk after NFKC normalisation and whitespace collapsing
   (`quote_not_found`, `verify.py:70-84`); a match that starts or ends inside a number, such as
   "EUR 1" inside "EUR 1,000", does not count (`verify.py:54-67`);
3. every number or date in the claim text appears in the claim's quotes (`numeric_mismatch`,
   `verify.py:101-103`).

Offsets of the matched span are mapped back into the extracted document text (`verify.py:105-117`) so
the UI can highlight them. The summary `answer` is kept only if each number in it is backed by a verified
claim, otherwise the verified claims are joined (`verify.py:121-127`). No verified claim means
abstention with `no_verified_claims` (`src/compliance_rag/graph/build.py:455-462`). Rejections are
reported with a reason and counted, not hidden (`build.py:362-365`).

## Alternatives considered

- **Free-form citations ("see section 4.2 of the KYC policy") with no check.** Rejected: nothing
  prevents a fabricated reference, and a reader cannot tell a real one from an invented one.
- **Citations validated by an LLM judge only.** Rejected as the gate: a model-based check is
  probabilistic and cannot be reproduced offline. A judge exists for evaluation (`FakeJudge` offline),
  not for deciding what reaches the user.
- **Fuzzy or embedding-similarity quote matching.** Rejected: it would accept paraphrases that change a
  number or a negation. The property tests show the intent: substrings under whitespace changes are
  accepted and single-character mutations are rejected
  (`tests/unit/graph/test_verify_citations.py`, `test_substrings_accepted_under_whitespace_changes`
  and `test_single_character_mutations_rejected`).

## Consequences

Positive:

- Hallucinated citations cannot be emitted: `hallucinated_citation_rate` is 0.000 (hard gate, n=95),
  `citation_precision` 1.000 and `stale_version_citation_rate` 0.000 (n=94) on the 120-case test split
  (`evals/REPORT.md` suite `rag`). These are offline numbers produced with the deterministic FakeLLM;
  they measure the pipeline, not a live model, as that report states.
- Each citation carries document, version and span, so a superseded version is visible as such
  (`src/compliance_rag/graph/respond.py:13-31`).

Negative:

- The check proves the quote exists and that numbers match; it does not prove the claim is entailed by the
  quote beyond those numbers. Faithfulness scoring with a live judge (Ragas) is not wired and no live
  eval has been run (`docs/KNOWN_LIMITATIONS.md`, Evals rows).
- A correct but paraphrased quote is rejected, which can cost an answer. Live behaviour is unmeasured;
  offline, `key_fact_accuracy` is 0.886 against a 0.85 gate (`evals/REPORT.md` suite `rag`), and
  rejection reasons are exposed as `claim_rejected` events and a metric so they can be monitored.
- Verification adds CPU work per claim; it runs inside the streaming loop (`build.py:367-395`), within
  the time-to-first-token budget of 300 ms, which passes offline with a worst-run p95 of 289.7 ms
  (`evals/reports/bench.json`, `nfr2_ttft.worst_p95_ms`). That margin is thin, and the figure uses the
  FakeLLM, so it excludes real model latency.
