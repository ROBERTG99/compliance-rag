---
paths: ["tests/**", "web/src/**/*.test.tsx", "web/src/**/*.test.ts"]
---
# Testing

- Write the failing test first, then implement (`tdd` skill).
- No network beyond loopback/private addresses: the socket guard in `tests/conftest.py` enforces the offline rule.
- Integration tests use `tests/integration/conftest.py` service fixtures (testcontainers, or `CRAG_TEST_*` URLs inside `compose.test.yaml`); one OpenSearch index per test.
- Seed 2026, frozen clock, poll instead of sleep.
- Never skip, xfail, weaken or delete a test or threshold to get green; fix the code or record the gap in `docs/KNOWN_LIMITATIONS.md`.
