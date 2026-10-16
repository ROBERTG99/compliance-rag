---
name: tdd
description: 'Test-driven loop for one task: write the failing test, implement, run checks, record evidence, commit.'
---

# TDD loop

1. Read the task in `PROGRESS.md` and its spec entry in `docs/specs/000-build-spec.md` (files, named test, done-when).
2. Write the named test first. Run it: `uv run pytest <path>::<test> -q` (or `pnpm -C web test <file>`). Confirm it fails for the right reason.
3. Implement the smallest change that makes it pass. Keep provider imports in the gateway and ACL inside queries.
4. Run the area checks: `make check-fast` plus the relevant integration tests.
5. Record evidence in `PROGRESS.md` (command + one-line result) and mark the task done.
6. Commit with a Conventional Commit message (no attribution trailers).
