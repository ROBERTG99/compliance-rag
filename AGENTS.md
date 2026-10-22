# AGENTS.md

Essentials for AI coding assistants working in this repository (Claude Code reads `CLAUDE.md`, which has the same rules and a full map).

- **What it is:** compliance policy Q&A with verified citations, per-document ACL, version validity and hybrid retrieval. Architecture: `docs/architecture.md`. Decisions: `docs/DECISIONS.md`, `docs/adr/`.
- **Setup:** `make bootstrap`, then `make check-fast` (fast loop) and `make verify` (full gate). Stack: `make up`.
- **Offline first:** tests, demo and `make verify` need no API keys (FakeLLM, LSA embedder, cassettes). Live calls only via `make eval-live` within `LIVE_EVAL_BUDGET_USD`.
- **Architecture rules:** provider SDKs only in `src/compliance_rag/llm/gateway.py`; every retrieval call takes a `Principal` and filters ACL/validity inside the query; unauthorized resources return 404; only verified claims stream.
- **Tests:** write the failing test first; never skip or weaken tests or eval thresholds; never edit existing `evals/datasets/*.jsonl`; tune on dev only.
- **Commits:** Conventional Commits. No Co-Authored-By, Claude-Session or "Generated with ..." trailers; never touch git identity configuration; never force-push.
- **Never:** deploy, run terraform apply/destroy, change repository visibility, message real people, commit secrets or real personal data.
