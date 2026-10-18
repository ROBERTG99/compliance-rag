# Verification

Final verification of BUILD.md §19 ([docs/specs/000-build-spec.md](specs/000-build-spec.md)), run on
2026-10-18 against commit `f636ecd` on branch `feat/practical-planck-8e2t30`. Every number below is copied
from the command output (`make verify-clean` log) or from the reports that run generated.

## Environment

| Item | Value |
|---|---|
| Host | Claude Code on the web cloud container: Linux 6.18.44, 4 vCPU (Intel Xeon @ 2.10 GHz), 15 GB RAM |
| Docker | 29.8.2, Compose 5.6.0 |
| Toolchain | Python 3.12.13, uv 0.11.32, Node 22.22.0, pnpm 10.28.0 |
| Keys | No `.env` in the clone; `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, AWS and Langfuse keys unset |
| Model | FakeLLM (offline); no live model was called |

## Step 1 and 2: `make verify-clean`

`scripts/verify_clean.sh` clones HEAD into a temporary folder, unsets the provider keys, uses its own compose
project (`crag-verify`, fresh volumes) and times each step. Started 2026-10-18T15:42:39Z, finished
2026-10-18T16:06:49Z, exit code 0:
`verify-clean: make verify, make demo and make test-docker passed in a fresh clone with no API keys`.

| Step | Duration | Result |
|---|---|---|
| `make bootstrap` | 5 s | rc 0 |
| `make up` (build, healthchecks, migrate, seed) | 176 s | rc 0; "stack healthy in 176s (budget 300s)" (NFR-7) |
| `make verify` | 747 s | rc 0 (parts below) |
| `make demo` | 2 s | rc 0; "demo ok" |
| `make test-docker` | 505 s | rc 0; 374 passed, 19 subtests passed in 392.62 s |

Parts of `make verify`, in order:

| Part | Result |
|---|---|
| `make lint` | ruff, ruff format, eslint, prettier, markdownlint, promtool: all checks passed |
| `make typecheck` | mypy strict, tsc, import-linter: passed (contract "Provider SDKs are imported only by the LLM gateway" kept) |
| `make security` | gitleaks, bandit, pip-audit, pnpm audit (web, red-team), hadolint, actionlint, licences, trivy on the four images: "security: all checks passed" |
| `make test` | 374 passed, 19 subtests passed in 447.25 s; coverage gate: graph 96.6%, retrieval 95.1%, rerank 95.0%, guard 100.0%, auth 97.7%, ingest 93.6% (each ≥ 85%), overall 90.8% (≥ 70%); web: 10 test files, 38 tests, lines 89.98% (≥ 70%) |
| `make e2e` | 8 passed (39.7 s), axe checks included |
| `make eval` | rag and retrieval suites on the test split (120 cases each): "all gates pass" |
| `make redteam` | 40 passed, 0 failed |
| `make bench` | NFR-1, NFR-2, NFR-3 and NFR-8 budgets passed (table below) |

Generated reports from this run (committed): [evals/REPORT.md](../evals/REPORT.md),
[evals/reports/latest.json](../evals/reports/latest.json), [evals/reports/redteam.json](../evals/reports/redteam.json),
[evals/reports/bench.json](../evals/reports/bench.json), [evals/reports/time_up.json](../evals/reports/time_up.json).

| Budget | Measured in this run | Limit |
|---|---|---|
| NFR-1 retrieval p95 (n 60) | 161.2 ms | < 300 ms |
| NFR-2 time to first verified claim p95 (n 59) | 260.6 ms | < 300 ms |
| NFR-8 `GET /v1/documents` p95 (n 120) | 17.5 ms | < 200 ms |
| NFR-3 ingestion lag p95, 24 documents through the worker | 3249.8 ms | < 300000 ms |

`bench.json` keeps every run of the configured stack, including earlier NFR-2 runs over budget (worst
395.7 ms); see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

Earlier attempts of this step failed and were fixed before this run (all recorded in
[DECISIONS.md](DECISIONS.md), 2026-10-18): concurrent LangGraph checkpointer migrations crashing an API worker
on a fresh database, a web formatting check, a gitleaks false positive, MinIO recompiling on every start
until the disk filled, cold in-process test apps timing out retrieval, and NFR-2 tail latency.

## Step 3: reviews

- `reviewer` over the whole history: "fix first" (four blockers: exception text in logs, MinIO-down 500,
  quotes outside the output guard, NFR-3 lag unmeasured), all fixed; re-reviews until "ship" at `5947b70`,
  then a delta review of `5947b70..f636ecd`.
- `security-review` over the branch: no findings at or above the reporting threshold.

## Step 4: live evaluation

Not run: no provider key is set in this environment. [evals/REPORT.md](../evals/REPORT.md) says so in its
"Live evaluation" section; the budget stop of `make eval-live` is tested offline (`tests/unit/evals/test_budget.py`).

## Step 5: authorship

```text
$ git log --format='%an <%ae> | %cn <%ce>' | sort -u
ROBERTG99 <54124633+ROBERTG99@users.noreply.github.com> | ROBERTG99 <54124633+ROBERTG99@users.noreply.github.com>
$ git log --format=%B | grep -E 'Co-Authored-By|Claude-Session|Generated with Claude Code'
(no output)
```
