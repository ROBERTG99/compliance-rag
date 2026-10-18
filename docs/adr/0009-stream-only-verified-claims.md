# 0009. Stream only verified claims, not raw model tokens

## Status

Accepted

## Date

2026-10-16

## Context

Users expect to see an answer appear while it is generated. In this system an answer is only trustworthy
after its citations pass verification (ADR 0005), and the model's output can be shaped by untrusted
document text: a prompt-injected sentence can make it emit a canary token, a link or an instruction
(`docs/DECISIONS.md`, 2026-10-17 row on the injectable FakeLLM). Anything sent to the browser cannot be
taken back, so unverified text on the wire is a risk in both correctness and security.

## Decision

The generate step asks the model for structured JSON and parses the stream incrementally: a
`ClaimStreamParser` yields each `claims[i]` object as soon as it closes
(`src/compliance_rag/graph/stream.py:10-61`). Each closed claim is then, in this order
(`src/compliance_rag/graph/build.py:367-395`):

1. schema-checked (`schema_invalid`);
2. run through the output guard against the context (`output_guard`);
3. verified against the context chunks (`quote_not_found`, `chunk_not_in_context`, `numeric_mismatch`).

Only a claim that passes all three is emitted as a `claim` event, followed by `token` events that
re-split its already verified text into six-word pieces (`build.py:392-395`). A rejected claim emits
`claim_rejected` with a reason and never its text (`build.py:362-365`). The final answer is built from
exactly the claims that streamed (`build.py:462-490`). The SPA only renders `claim` events and ignores
`token` events (`web/src/routes/ask/run.ts:35`). Events go through Redis Streams with ids `0-<seq>` so a
client can resume after a drop (`src/compliance_rag/api/sse.py:1-6`).

## Alternatives considered

- **Stream raw model tokens, verify at the end.** Rejected: unverified or injected text would already be
  on screen, and the ACL, canary and number checks would run too late. A retraction cannot unsee text.
- **Stream raw tokens with an "unverified" label.** Rejected: the label does not stop a user from acting
  on a wrong figure, and a canary or exfiltration URL would still be delivered.
- **Buffer the whole answer and send it once.** Rejected: it is the safest option but gives no early
  feedback, and time to first useful content would be the full generation time. Claim-level streaming
  keeps most of the benefit.

## Consequences

Positive:

- Nothing unverified reaches a client: `test_answer_streams_only_verified_claims` and
  `test_canary_in_claim_text_is_never_streamed` (`tests/unit/graph/test_graph.py`) pin this, and the
  offline red-team reports 40 attacks with 0 failures (`evals/REPORT.md` "Red-team").
- The streamed claims and the final answer agree
  (`test_final_answer_matches_streamed_claims_when_one_claim_is_invalid`).
- Time to first token is measured at the first verified claim (`build.py:387-389`). Offline, p95 is
  231.5 ms against a 300 ms budget, with a worst-run p95 of 289.7 ms (`evals/reports/bench.json`,
  `nfr2_ttft`). It uses the FakeLLM, so real model latency is not included.

Negative:

- The first visible text waits for a complete claim and its verification, not for the first model token.
  With a live model the wait is the time to produce one full claim; no live figure exists
  (`docs/KNOWN_LIMITATIONS.md`, Evals rows).
- A claim can still be withdrawn after it streamed: if the model refuses mid-stream, or the final
  re-check drops a claim, the server emits `claim_rejected` with reason `retracted`
  (`build.py:405-407`, `build.py:477-478`) and the UI removes it by index
  (`web/src/routes/ask/run.ts:75-78`). A `max_tokens` stop keeps the verified claims as a partial answer
  flagged `generation_truncated` (`build.py:488-489`).
- The `token` events are a presentation effect over verified text, not model tokens, so they add
  events without adding information.
- The parser skips an object that does not parse as JSON (`stream.py:53`) instead of reporting it. If the
  model emits no parseable claim, the run abstains with `no_verified_claims`.
- If Redis fails mid-run, a client behind the last sequence cannot resume and relies on the
  authoritative `final` event (`docs/KNOWN_LIMITATIONS.md`, Streaming row).
