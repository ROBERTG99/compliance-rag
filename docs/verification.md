# Verification

Record of the final verification of BUILD.md §19 ([docs/specs/000-build-spec.md](specs/000-build-spec.md)):
every command, its result and duration, run on a fresh clone with no `.env` file and no API keys.

**Status: pending.** This page is filled in by task T-51 from the actual command output. Until then,
per-task evidence is in [PROGRESS.md](../PROGRESS.md).

## Procedure

1. Commit everything, then `make verify-clean`: clones the repository into a temporary folder and, with no
   `.env` and the provider keys unset, runs `make bootstrap && make verify` there under a separate compose
   project name.
2. In the clone: `docker compose up -d --wait`, `make seed`, `make demo`, `make e2e`, `make test-docker`,
   then `docker compose down -v`.
3. Reviews over the whole history: the `reviewer` subagent, then the security and code reviews; every
   blocker fixed and steps 1–2 repeated.
4. Live evaluation only if a provider key is set (`make eval-live`); otherwise the report says it was not
   run.
5. Authorship over the whole history:
   `git log --format='%an <%ae> | %cn <%ce>' | sort -u` and
   `git log --format=%B | grep -E 'Co-Authored-By|Claude-Session|Generated with Claude Code'`.
