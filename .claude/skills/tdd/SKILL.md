---
name: tdd
description: 'Test-driven loop for one change: write the failing test, implement, run checks, commit.'
---

# TDD loop

1. Read the issue or request and identify the files, the behaviour to test and the done-when condition.
2. Write the named test first. Run it: `uv run pytest <path>::<test> -q` (or `pnpm -C web test <file>`). Confirm it fails for the right reason.
3. Implement the smallest change that makes it pass. Keep provider imports in the gateway and ACL inside queries.
4. Run the area checks: `make check-fast` plus the relevant integration tests.
5. Note the commands you ran and their results in the commit or pull request description.
6. Commit with a Conventional Commit message (no attribution trailers).
