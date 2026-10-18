# How the spec and harness drove the build

This repository was built by an AI coding agent (Claude Code, running on the web) working from a written specification, inside a harness of rules, hooks, subagents and skills that the spec itself asked for. This page describes that process and the mistakes it produced and caught. It is written from the repository's own records: [PROGRESS.md](../PROGRESS.md), [DECISIONS.md](DECISIONS.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md), the `.claude/` directory and `git log`. Where a claim comes from somewhere else, the text says so.

State when this page was written: tasks T-01 to T-46 are marked done in [PROGRESS.md](../PROGRESS.md), T-47 to T-51 (images and compose, CI, documentation, final reviews, final verification) are still `todo`, and every box in the Global Definition of Done in that file is unchecked. The branch had 81 commits (`git log --oneline | wc -l`), of which 22 start with `fix` (`git log --oneline | grep -cE '^[0-9a-f]+ fix'`). This page describes a build in progress, not a finished and verified release.

## 1. The spec as the driver

The build started from one document, [docs/specs/000-build-spec.md](specs/000-build-spec.md) (the copy of `BUILD.md`, which also still sits at the repository root until the final task moves it). It describes itself as the complete specification, and it contains:

- Operating rules (section 0): do not stop early, decide instead of asking and log the decision, keep progress in the repository, write the failing test first, never skip or weaken a test or threshold, work offline, never invent numbers, never change git identity or add attribution trailers, run the `reviewer` subagent at the end of every milestone.
- Product brief and requirements (sections 2 and 3): 14 functional requirements (FR-1 to FR-14), each with a Given/When/Then and a named test, and 9 non-functional requirements (NFR-1 to NFR-9) with the command that measures each.
- A work plan (section 8) of 51 tasks, T-01 to T-51, in milestones M0 to M9 (`grep -o '\*\*T-[0-9]*' docs/specs/000-build-spec.md | sort -u | wc -l`). Each task lists its files, the test to write first, a "done when" condition and its dependencies.
- A Definition of Done (section 9): per task (test fails first, then passes; evidence recorded; one Conventional Commit), per milestone (all tasks done, `make check-fast` green, `reviewer` without blockers) and a global checklist.
- Evaluation thresholds (section 11), the harness inventory (section 7), the documentation deliverables (section 18, which includes this page) and the final verification procedure (section 19).

The spec also fixes a blockers protocol (section 20): outside four listed cases the agent was told to degrade gracefully and keep going. Because "nobody will answer questions while you work" (section 0), ambiguity had to be resolved by the agent and written down, which is what [DECISIONS.md](DECISIONS.md) is for.

The per-task loop is encoded in the `tdd` skill (`.claude/skills/tdd/SKILL.md`): read the task, write the named test and confirm it fails for the right reason, implement the smallest change, run `make check-fast` and the relevant integration tests, record the command and a one-line result in [PROGRESS.md](../PROGRESS.md), commit with a Conventional Commit message.

## 2. The ledger: PROGRESS, DECISIONS, ADRs

Three files carry state between sessions. The build ran over more than one session and the repository records two handoffs: the 2026-10-16 "Session handoff" row in [DECISIONS.md](DECISIONS.md) and the "Resume here (handoff, 2026-10-17)" section of [PROGRESS.md](../PROGRESS.md). The spec tells a restarted agent to re-read the spec, `PROGRESS.md`, `docs/DECISIONS.md` and `git log --oneline -30`, then resume from the first unchecked task.

- [PROGRESS.md](../PROGRESS.md) has a "Needs the maintainer" list at the top, milestone review verdicts, a task table (ID, milestone, title, status, evidence) and the Global Definition of Done. The evidence column holds the command that was run and what it printed, for example the T-46 row with the three `make bench` runs.
- [DECISIONS.md](DECISIONS.md) is a table of date, decision, alternatives and reason: 70 rows when this page was written (`grep -c '^| 20' docs/DECISIONS.md`). Many reasons start with a review finding, for example "M2 review:" or "ACL audit:", so the log doubles as a record of what review changed.
- [docs/adr/](adr/) holds the nine ADRs the spec lists (pgvector default, OpenSearch BM25, RRF, ACL pre-filter, verified extractive citations, local LSA embedder, Arq, Vite SPA, streaming only verified claims).
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) takes the gaps that were accepted instead of fixed. The testing rules forbid skipping or weakening a test to get green, so a gap is written there instead.

Each task ends in one Conventional Commit. A review fix is a separate `fix(...)` commit whose subject names the milestone, for example `0238654 fix(evals): M5 review: ...`.

## 3. The harness

### Context loaded into every session

- [CLAUDE.md](../CLAUDE.md) holds the system summary, the source map, the `make` targets, conventions (provider SDKs only in `llm/gateway.py`, ACL inside every query, 404 for unauthorized resources, only verified claims stream), testing rules and a "never do" list. [AGENTS.md](../AGENTS.md) carries the same essentials for other agents.
- `.claude/rules/` has ten files: `git-commits.md` always loads; the other nine (`python`, `frontend`, `llm-code`, `testing`, `evals`, `docker`, `security`, `docs`, `retrieval`) load only when the agent touches matching paths, for example `retrieval.md` for `src/compliance_rag/retrieval/**`.
- `.claude/settings.json` sets a blank commit and PR attribution, an allow list (`make *`, `uv run *`, `pnpm *`, `docker compose *`, a few `git` commands, `crag *`) and a deny list (reading `.env` and `.env.*`, force pushes, `rm -rf /*` and `rm -rf ~*`).

### Hooks

Four hooks are registered in `.claude/settings.json`; their behaviour below is read from the scripts, and `tests/harness/test_hooks.py` tests them.

- `session_start.sh` (SessionStart) does nothing unless `CLAUDE_CODE_REMOTE=true`. In a web session it starts `dockerd` with a registry mirror if Docker is not running, runs `scripts/install_tools.sh` (gitleaks, actionlint, hadolint, trivy), then `uv sync --frozen` and `pnpm -C web install --frozen-lockfile`. It always exits 0.
- `pre_tool_guard.py` (PreToolUse on Bash, Write, Edit) blocks with exit code 2. It splits a command into segments on `;`, `&&`, `||`, `|` and newlines, tokenises each with `shlex`, and ignores heredoc bodies. It blocks attribution text (`Co-Authored-By`, `Claude-Session`, "Generated with Claude Code") in `git commit`, including inside a `-F` message file, and in `gh pr` commands; changes to the git identity (`git config user.*`, `git -c user.*`, `--author`, `GIT_AUTHOR_*` and `GIT_COMMITTER_*` assignments); force pushes (`--force*`, combined short flags containing `f`, `+refspec`); `gh repo create|delete|fork|rename|archive` and visibility changes; `terraform apply|destroy`; recursive `rm` of `/` or `~`; and any write (redirect, `tee`, `rm`, `mv`, `cp`, `sed -i`, or a Write/Edit call) to an existing `evals/datasets/*.jsonl` file. New versioned dataset files are allowed. It fails open: malformed input or an internal error never blocks a call.
- `post_edit_format.py` (PostToolUse on Write, Edit) runs `ruff format` on Python files and `prettier --write` on web files under `web/`. It is a no-op when the tool is missing and never fails the tool call.
- `stop_check.py` (Stop) runs `make check-fast` with a 60 second timeout. If it fails, the hook returns a `block` decision with the last 15 lines of output so the agent keeps working. It honours `stop_hook_active`, so it asks only once, and a timeout does not block.

### Subagents and skills

Eight subagents live in `.claude/agents/` and thirteen skills in `.claude/skills/` (the counts match the T-06 row of [PROGRESS.md](../PROGRESS.md)).

| Subagent | Tools | What it does | Use recorded in PROGRESS or DECISIONS |
|---|---|---|---|
| `reviewer` | read-only | Reviews a git range at the end of a milestone against the spec, correctness, security invariants, test quality, honesty of numbers and commit hygiene; answers "ship" or "fix first" | Milestones M0 to M6 and re-reviews of M2, M3, M4 |
| `ux-reviewer` | read-only | Checks the web UI against the design tokens, four screen states and WCAG 2.2 AA | M4 ("fix first", then fixed) |
| `retrieval-reviewer` | read-only | Reviews chunking, fusion, reranking and eval methodology for dev/test leakage | M5 ("no blockers") |
| `acl-auditor` | read-only | Traces every path from a `Principal` to the SQL, OpenSearch and Qdrant filters and the API responses | DECISIONS cites an "ACL audit" for several fixes; the agent is not named |
| `security-auditor` | read-only | OWASP Top 10 for LLM applications, secrets, dependencies | No use recorded |
| `test-designer` | writes tests only | Writes tests for a behaviour and shows them failing | No use recorded |
| `eval-analyst` | read-only | Analyses eval failures on the dev split only | No use recorded |
| `docs-editor` | writes docs | Edits documentation and checks that numbers cite a source | No use recorded |

The skills are procedures for repeated jobs: `tdd`, `quality-gate`, `eval-report`, `new-adr`, `add-migration`, `add-endpoint`, `add-retrieval-leg`, `add-eval-case`, `demo-capture`, `release`, `add-corpus-domain`, `run-ablation` and `debug-retrieval`.

### Mechanical gates

Rules written in prose can be ignored, so the important ones also exist as code.

- **Socket guard.** `tests/conftest.py` patches `socket.connect` so tests may reach loopback, unix sockets and private addresses (testcontainers, the compose test network) and nothing else. It removes provider API keys from the test environment and defaults to the fake LLM, so the suite runs offline (NFR-9).
- **Import contract.** `[tool.importlinter]` in `pyproject.toml` forbids `anthropic` and `openai` imports everywhere except `llm/gateway.py`; `make typecheck` runs `lint-imports`, and `tests/harness/test_import_contract.py` covers it.
- **Dataset immutability.** The pre-tool hook blocks edits to existing `evals/datasets/*.jsonl`, and a unit test fails if the committed datasets drift from the generator.
- **`make check-fast`.** ruff, ruff format check, `mypy --strict` and the unit and harness tests (target under 60 seconds). The Stop hook and `scripts/task_commit.sh` both run it.
- **`make verify`.** Chains lint, typecheck, security, test, e2e, eval, redteam and bench; `make verify-clean` runs it in a fresh clone. Neither had been run to completion when this page was written (Global Definition of Done unchecked in [PROGRESS.md](../PROGRESS.md)).
- **Eval gates.** `make eval` checks the thresholds in `evals/suites/*.yaml` and a stored baseline; ACL leakage and hallucinated citation rate are hard gates (T-39 row of [PROGRESS.md](../PROGRESS.md)).

## 4. Review cadence

The spec requires a `reviewer` run at the end of every milestone. This is how the verdicts are recorded in the milestone table of [PROGRESS.md](../PROGRESS.md):

| Milestone | Recorded outcome |
|---|---|
| M0 | "ship" after fixes (guard rewritten, see mistake 1) |
| M1 | "ship", with follow-ups applied |
| M2 | Five reviewer blockers; "ship" on re-review after `e847e0f`, `6047fd5`, `8cb824a` |
| M3 | Blockers fixed; "ship" on re-review after `302e3d8` to `3f8d73e` and follow-ups |
| M4 | `reviewer` blocker fixed, "ship" on re-review; `ux-reviewer` "fix first", then fixed |
| M5 | `reviewer` "fix first"; `retrieval-reviewer` no blockers; fixed in `0238654` |
| M6 | `reviewer` "fix first"; fixed in `168c7b4`; no re-review is recorded |

M7 to M9 have not started, so no verdict exists for them, and the final whole-history review that section 19 of the spec asks for has not happened.

## 5. Mistakes that were made and caught

Each entry says what went wrong, how it was found and what fixed it. All twelve are recorded in the sources named in the entry. Commit messages in this repository are subject lines only, so the detail comes from [PROGRESS.md](../PROGRESS.md) and [DECISIONS.md](DECISIONS.md).

### 1. The harness had bugs of its own (M0)

Two separate problems. First, the hooks were registered in `.claude/settings.json` before their scripts existed. Settings reload live, so the missing PreToolUse script blocked every Bash, Write and Edit call. With the maintainer's go-ahead, placeholder scripts were created, then replaced by the real hooks in T-05; `CLAUDE.md` now has a "never do" line for it (DECISIONS, 2026-10-16, "Hooks were registered ..."). Second, the first version of the pre-tool guard used regexes over the whole command. The M0 `reviewer` found false positives (`--rm`, `2>&1`, `cp v1 v2`) and misses (`--author`, `-c user.*`, `-fu`). The fix, `64465b6`, is the per-segment tokeniser described above (DECISIONS, 2026-10-16, "Pre-tool guard tokenises ..."). The guard still cannot see a dataset write made from inside a program such as `python -c "open(...,'a')"`; that is in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) with the drift test as the backstop.

### 2. The first reranker fit over-abstained, then under-abstained (M2)

The first fit of the feature reranker abstained too often (key-fact accuracy 0.674 on dev), and after one change it abstained too rarely on ACL probes (0.111). Both were seen by measuring on the dev split; the logistic weights and the abstention threshold were then adjusted on dev only, never on test. DECISIONS (2026-10-16, "FeatureReranker features") records the sequence; the T-21 row of [PROGRESS.md](../PROGRESS.md) records the final dev numbers. Commits: `01e3712`, `46f7488`.

### 3. Claim streaming let unverified text and bad numbers through (M2 review)

The M2 `reviewer` found that one invalid claim used to abstain after valid claims had already streamed, that claim texts bypassed the output guard, and that a truncated quote ("EUR 1" inside "EUR 1,000") passed substring matching and let a claim state a different number. It also found that provider embedding and rerank calls blocked the event loop (defeating the 250 ms leg timeout) and skipped PII redaction, and that BM25-sourced citations carried chunk-relative offsets. Fixes: each streamed claim is schema-checked, output-guarded and verified before it is emitted, and the final answer is built from exactly the streamed claims; quotes that start or end inside a number are rejected (`e847e0f`); provider clients go through redacting wrappers off the event loop and OpenSearch stores `char_start`/`char_end` (`6047fd5`). Sources: DECISIONS 2026-10-16 rows beginning "`claim_rejected.reason` adds", "Quote matching rejects", "Provider embedding/rerank clients" and "OpenSearch stores".

### 4. The ACL audit found writes that widened or reopened access (M2)

An ACL audit (named only as "ACL audit" in DECISIONS) found that a narrowing re-upload succeeded while the broader ACL stayed in place, that activation reopened retired versions in Postgres while OpenSearch kept them closed, and that update-by-query against a concrete index could silently lose ACL or visibility updates after a reindex, while a crashed seed could expose pending versions. Fix: `8cb824a`, with ACL-changing uploads rejected (409/422), explicit `valid_to` kept, alias-safe index updates and a seed that writes chunks invisible and flips visibility after the Postgres commit. Sources: DECISIONS 2026-10-16 rows "Uploads whose `acl_groups` differ", "Activation keeps an explicit `valid_to`" and "OpenSearch update/delete-by-query target the alias".

### 5. M3 blockers: SSE reads, an ACL race and a stale revocation

The M3 review found that SSE reads collided with the Redis socket timeout (fix `302e3d8`) and that an ACL change could race ingestion while a 409 upload could overwrite raw bytes (fix `561b7c1`). Follow-up review items led to `b10f6db`: index hits are re-checked against Postgres for ACL, visibility and validity, ACL changes and their audit row commit together, and an index sync that fails stays pending and is retried by a one-minute cron instead of being marked failed, so a revocation that has not reached an index is never served and eventually reaches it (DECISIONS, 2026-10-17, "Index hits from OpenSearch and Qdrant are re-checked"). The PROGRESS M3 row lists the rest.

### 6. Cold caches turned into 503s (M3 to M5)

After a restart, the first pgvector query took about 2.1 s and both retrieval legs could exceed the 250 ms budget, so asks returned 503 `retrieval_unavailable` ([KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md), Retrieval row). It was found while building the seed and demo task (T-33 row), and again when the first dev smoke run of the retrieval suite failed 9 of 20 cases with cold-cache `RetrievalUnavailable` ([PROGRESS.md](../PROGRESS.md), T-39 next steps; DECISIONS, 2026-10-17, "Eval targets and the API share one cache warm-up"). The fix was a warm-up before the API reports ready (`4fe8fbf`) shared with the eval targets (`cd95f4a`), not a longer timeout, because the 250 ms budget is a spec value. A full disk produced the same 503s in a different way; that is in the environment notes of [PROGRESS.md](../PROGRESS.md).

### 7. A persona switch leaked restricted data in the browser (M4 review)

The M4 `reviewer` reproduced a leak of a restricted row and a restricted answer after an in-page persona switch. The fix, `cee74cb`, clears the whole query cache and remounts the ask run on every token change and signs out on 401 or expiry (DECISIONS, 2026-10-17, "The SPA clears the whole TanStack Query cache"). The same review round (`b57cf9c`) made the persona switcher opt-in so that it is not part of a non-dev build by accident. Follow-ups after the re-review (`85eac8e`) include abstention screenshots that had captured the loading skeleton instead of the abstention text ([PROGRESS.md](../PROGRESS.md), M4 row).

### 8. Two ways the eval harness measured the wrong thing (M5)

On the first test-split run, the retrieval suite and the RAG suite disagreed on one case (recall@10 0.932 against 0.920) because the retrieval target reranked every fused candidate while the graph reranks only the top `leg_k`. The target was changed to apply the same cut, without changing any system parameter (DECISIONS, 2026-10-17, "`RetrievalTarget` reranks only the top `leg_k`"). Separately, running four questions concurrently on the 4-core dev box pushed retrieval p95 to about 720 ms and caused leg timeouts that the recall metric hid; the suites now run one question at a time and load behaviour is left to `make bench` (DECISIONS, 2026-10-17, "Eval suites run one question at a time"). The first of these was found on a test-split run, so the test split was used to find a harness bug, not only to report.

### 9. The offline red-team could not fail (M5 review)

The M5 `reviewer` blocked on two things. `eval-live` could not stop for a model with no price, so the budget stop could be bypassed; it now refuses unpriced models. And the red-team could not notice a missing context guard: the fake model obeyed canary instructions it saw, but the output guard blocked the canary anyway, so removing `guard_context` left every canary assertion green. The unit test from T-41 already failed with `guard_context` disabled; the gap was in `make redteam`. The fix added a gate on how many injected documents are still answered with their fact, against `evals/redteam/baseline.json` (28 of 30). DECISIONS had described the earlier behaviour wrongly and was corrected. Commit `0238654`; sources: M5 row of [PROGRESS.md](../PROGRESS.md) and DECISIONS 2026-10-17 rows "The offline FakeLLM is deliberately injectable" and "Red-team: Promptfoo".

### 10. M6 blockers: text kept forever and metrics from one worker (M6 review)

The M6 `reviewer` found that the retention job left LangGraph checkpoints, which hold question and context text, in the database indefinitely, and that `/metrics` with three API workers reported one process per scrape, which broke `increase()` alerts through counter resets. Fixes in `168c7b4`: checkpoints are deleted with the conversation's last answer in the same transaction (`tests/integration/test_retention.py`), and Prometheus multiprocess mode aggregates the workers (`tests/unit/obs/test_multiprocess.py`). The same review added stuck-queue and worker-down alerts with `promtool test rules`, made logs and exported spans scrub text at any depth, and fixed a re-upload after job purge that re-indexed an active version (DECISIONS, 2026-10-17, "M6 review").

### 11. The first benchmark was too kind (M6)

The first `make bench` runs failed on time to first verified claim: with one uvicorn process the p95 was about 470 ms against a 300 ms budget (DECISIONS, 2026-10-17, "`make bench` measures NFR-1/2/8"). The fixes were caches for the reranker's per-chunk term sets and vectors, three API workers (`1d79a61`) and a start-up preload of those caches. The first passing numbers (NFR-1 p95 99.6 ms, NFR-2 200.0 ms, recorded in the T-46 row at `1d79a61`) then turned out to come from warming up on the same questions that were timed, which measures the best case. The M6 review asked for a warm-up on other questions, every run kept in the report, and a test that injects 400 ms into the real rerank node and checks the same measurement code fails both budgets. Reported numbers got worse and more honest: three runs of NFR-1 p95 at 126.3, 130.9 and 126.0 ms and NFR-2 p95 at 277.5, 289.7 and 231.5 ms against 300 ms budgets (`evals/reports/bench.json`, `168c7b4`). The worst NFR-2 run is 10.3 ms under its budget, and the benchmark runs on a shared 4 vCPU container with the offline fake model, so it says little about a live deployment (see section 7).

### 12. The commit helper hid failures and swept in unrelated files

`scripts/task_commit.sh` formats, runs `make check-fast`, refuses to commit on red, then runs `git add -A`. Two slips are visible. [PROGRESS.md](../PROGRESS.md) records that piping `make check-fast` into `tail` hid its exit code and let one red commit through, "fixed in the next commit"; the style-only commit `47bce4a` ("format the ingestion race tests") directly follows `561b7c1` and looks like that fix, but the record does not name it, so that link is an inference. The second slip is not recorded as a mistake in the ledger; it shows in the commit's file list. `git show --diff-filter=A --name-only 168c7b4` lists `compose.test.yaml`, `docker/tests.Dockerfile` and `tests/harness/test_compose.py` among the files the M6 review commit added. The spec assigns those files and that test file to T-47, which [PROGRESS.md](../PROGRESS.md) still lists as `todo`, so they appear to have been swept in by `git add -A`. One commit per task was the rule; here, one commit holds work from two tasks. History was not rewritten.

## 6. Who did what

The repository does not keep the conversation, so this split is reconstructed from the spec, the ledger and the commit log, and it is incomplete.

- **The maintainer** wrote the specification and its constraints: scope, the fictional Northwind Payments tenant, the thresholds, the safety rails, the commit attribution rule and the harness inventory. The initial commit (`1df4707`) contains the spec and a scaffold. The maintainer's recorded interventions in the ledger are small: the go-ahead to create placeholder hook scripts (mistake 1), a request to pause and hand off to a new session (DECISIONS, 2026-10-16, "Session handoff"), and the open items in the "Needs the maintainer" list of [PROGRESS.md](../PROGRESS.md) (publishing a tag for the eval runner subset, reviewing 40 questions, running anything that needs provider keys). Commits are authored under the maintainer's identity by design (spec section 1.1), so the log does not distinguish human from agent work.
- **The agent** did the implementation: code, tests, migrations, the synthetic corpus generator, the web app, evals, observability, the harness files, and the ledger entries. It chose the options recorded in [DECISIONS.md](DECISIONS.md) as the spec instructed, ran the review subagents, and fixed their findings.
- **No live model was evaluated.** No provider key was available in the build, so every eval number is produced by the deterministic fake model, the local embedder and recorded fixtures. `make eval-live` was never run ([PROGRESS.md](../PROGRESS.md), "Needs the maintainer"), the Titan, OpenAI and Cohere fixtures are synthetic ([KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)), and Ragas faithfulness is not implemented.

## 7. Limits of the approach

- **The tests and the code came from the same author.** Test-first does not help when the agent forgets the same case twice. Most of the mistakes above (3, 4, 5, 7, 9, 10) passed the agent's own tests and were found by a milestone review, then covered by a new test. The review caught them, but it caught them after the fact, in batches at milestone boundaries.
- **The reviewers are models too.** The subagents have fresh context and read-only tools, which makes them useful, but they are not independent human reviewers. The only human review of the eval data, 40 questions, is still pending, and the question labels are "by construction" ([KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)).
- **Offline numbers are not model quality.** Results in [evals/REPORT.md](../evals/REPORT.md) are produced with the fake model and a corpus generated by the same project. They test the retrieval, verification and ACL code, not how a live model behaves. The dev/test split is by question, not by document: 52 of 160 gold documents serve both splits ([KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)).
- **Reviews are uneven.** Four of the eight subagents have no recorded use. The M6 fixes were re-reviewed only together with M7 and M8 (PROGRESS, "Milestone reviews"). The security scan and the threat model were produced by the agent that wrote the code.
- **The ledger drifts.** Until it was rewritten on 2026-10-18, the "Resume here" section of [PROGRESS.md](../PROGRESS.md) still said to re-run the M4 review and that T-39 was in progress, while the milestone table and the task table showed M4 re-reviewed and T-39 to T-46 done. A restarted agent that trusted the older paragraph would have redone work.
- **Hooks do not cover everything.** The pre-tool guard works on command text and cannot see what a program writes. `Read(.env.example)` is blocked by the broader deny rule ([KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)).
- **Autonomy has a cost.** "Decide, don't ask" produced 70 recorded decisions in about two days of commits (45 commits dated 2026-10-16 and 36 dated 2026-10-17 in `git log`), some of which were later superseded or corrected (for example the chart choice in DECISIONS rows 52 and 57, and the red-team description in the M5 row of PROGRESS). A maintainer who reads the log can see them; a maintainer who does not may inherit choices they would not have made.
- **Not finished.** CI workflows, final images, the documentation set, the whole-history review and `make verify-clean` are still to do, so none of the claims on this page have been confirmed by the clean-clone verification the spec requires.

## 8. Where to look

- The spec: [docs/specs/000-build-spec.md](specs/000-build-spec.md), sections 0, 7, 8 and 9.
- The ledger: [PROGRESS.md](../PROGRESS.md), [DECISIONS.md](DECISIONS.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
- The harness: [CLAUDE.md](../CLAUDE.md), `.claude/settings.json`, `.claude/hooks/`, `.claude/agents/`, `.claude/skills/`, `.claude/rules/`.
- The review fixes: `git log --oneline | grep -iE 'M[0-9] (re-)?review'` for milestone-review commits, and `git log --oneline` generally for the rest.
