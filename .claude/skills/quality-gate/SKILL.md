---
name: quality-gate
description: 'Run the full quality gate (make verify or its parts) and summarise results without dumping logs.'
---

# Quality gate

1. `make lint`, `make typecheck`, `make security` — fix findings or document accepted ones in `docs/security.md`.
2. `make test` — unit, integration, contract, harness; coverage ≥ 85% on core packages, ≥ 70% overall (`scripts/check_coverage.py`).
3. `make e2e`, `make eval`, `make redteam`, `make bench` against the running stack (`make up`).
4. Summarise: one line per step with pass/fail and duration. Write long output to files under `/tmp` and quote only the failing lines.
5. Never skip a failing step; fix the cause.
