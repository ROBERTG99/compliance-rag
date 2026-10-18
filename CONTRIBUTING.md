# Contributing

Thanks for looking at compliance-rag. Everything here runs locally and offline; you need Docker with
Compose, `uv`, `pnpm` and GNU make, and no API keys.

## Getting started

```bash
make bootstrap     # uv sync, pnpm install, .env from .env.example, lint/security CLIs
make up            # the stack with healthchecks, migrations and the synthetic seed
make check-fast    # ruff, mypy, unit and harness tests
```

[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers the local setup and sign-in, and
[docs/runbook.md](docs/runbook.md) covers operating the stack.

## Workflow

1. **Test first.** Write the test that describes the change and see it fail, then make it pass. Integration
   tests use the service fixtures in `tests/fixtures_services.py` (testcontainers, or the `CRAG_TEST_*`
   URLs inside `compose.test.yaml`).
2. **Small increments.** One logical change per commit, in
   [Conventional Commits](https://www.conventionalcommits.org/) form (`feat(retrieval): ...`,
   `fix(api): ...`, `docs: ...`).
3. **Run the checks** before pushing: `make check-fast` always; `make test` when you touch code with
   integration tests; `make eval` when you touch retrieval, reranking, prompts or the graph; `make e2e` for
   the web app. `make verify` runs everything.
4. **Record decisions.** A choice someone might later question goes in
   [docs/DECISIONS.md](docs/DECISIONS.md); an architectural one gets an ADR in [docs/adr/](docs/adr/). A
   gap you cannot close goes in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

Pull requests follow `.github/pull_request_template.md`. CI runs lint, types, unit and integration tests,
end-to-end tests, offline evals and the red-team, image builds with a vulnerability scan, and CodeQL.

## Rules that are enforced

- **Permissions inside every query.** Every retrieval function takes a `Principal`; there is no unfiltered
  search. Unauthorized resources answer 404, and restricted and unknown topics produce byte-identical
  abstentions.
- **One door to the providers.** Only `src/compliance_rag/llm/gateway.py` imports provider SDKs
  (import-linter contract, checked by `make typecheck`).
- **Offline tests.** A socket guard blocks every non-local connection in tests; use the FakeLLM, the LSA
  embedder and cassettes.
- **Never weaken a gate.** Do not skip, xfail or loosen a test or an eval threshold to get green; fix the
  cause or record the gap.
- **Datasets are append-only.** Do not edit an existing `evals/datasets/*.jsonl`; add a new `.vN` file.
  Tune only on the dev split.
- **Synthetic data only.** No real personal data, no secrets in the repository (`make security` runs
  gitleaks).
- **Numbers come from reports.** Every figure in the README and docs links to the report or command that
  produced it (`tests/harness/test_docs.py`).
- **Settings** come from `compliance_rag.settings.Settings` (`CRAG_` prefix), and every variable is
  documented in `.env.example`.

## Reporting security issues

Please do not open a public issue; see [SECURITY.md](SECURITY.md).
