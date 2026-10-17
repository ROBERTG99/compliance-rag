# compliance-rag — single entry point for every workflow (BUILD.md §16).
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PY := $(UV) run
PNPM ?= pnpm
COMPOSE ?= docker compose
COMPOSE_TEST := $(COMPOSE) -f compose.yaml -f compose.test.yaml
API_URL ?= http://localhost:8610
WEB_URL ?= http://localhost:8600
CORE_COV := --cov=compliance_rag --cov-report=term:skip-covered --cov-report=xml
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD ?= 1

.PHONY: help bootstrap up down seed demo logs check-fast test test-docker e2e eval eval-live bench \
	lint typecheck security verify verify-clean docs clean migrate corpus fit-reranker reindex \
	eval-ablation redteam calibrate-judge record-fixtures replay-failed-jobs stack-ready coverage \
	format tools

help: ## List targets
	@grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
bootstrap: ## Install toolchains and dependencies, create .env from .env.example
	$(UV) sync --frozen
	$(PNPM) -C web install --frozen-lockfile
	@test -f .env || cp .env.example .env
	./scripts/install_tools.sh

tools: ## Install the security/lint CLIs (gitleaks, actionlint, hadolint, trivy)
	./scripts/install_tools.sh

# ---------------------------------------------------------------- stack
up: ## Start the full stack (healthchecked) and seed it
	./scripts/time_up.sh

down: ## Stop the stack
	$(COMPOSE) --profile qdrant --profile observability --profile langfuse down --remove-orphans

stack-ready: ## Start the stack only if the API is not healthy yet
	@curl -sf $(API_URL)/readyz >/dev/null 2>&1 || $(MAKE) up

seed: ## Load the synthetic dataset with seed 2026 (idempotent)
	$(COMPOSE) run --rm seed

demo: ## Run the scripted demo scenario against the running stack, offline
	$(PY) python scripts/demo.py --api $(API_URL)

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=100

migrate: ## Alembic upgrade head
	$(PY) alembic upgrade head

# ---------------------------------------------------------------- quality
format: ## Apply formatters
	$(PY) ruff format src tests scripts data apps third_party migrations
	$(PY) ruff check --fix src tests scripts data apps third_party migrations

lint: ## ruff, eslint, prettier, markdownlint
	$(PY) ruff check src tests scripts data apps third_party migrations
	$(PY) ruff format --check src tests scripts data apps third_party migrations
	$(PNPM) -C web lint
	$(PNPM) -C web format:check
	$(PNPM) -C web exec markdownlint-cli2 --config ../.markdownlint-cli2.yaml

typecheck: ## mypy --strict, tsc --noEmit, import-linter
	$(PY) mypy
	$(PY) lint-imports
	$(PNPM) -C web typecheck

security: ## gitleaks, bandit, pip-audit, pnpm audit, hadolint, trivy, actionlint, licences
	./scripts/security.sh

check-fast: ## ruff + mypy + unit tests (< 60 s)
	$(PY) ruff check src tests scripts data apps third_party migrations
	$(PY) ruff format --check src tests scripts data apps third_party migrations
	$(PY) mypy
	$(PY) pytest tests/unit tests/harness -q -x -p no:cacheprovider

test: ## Unit, integration and contract tests on the host (testcontainers)
	$(PY) pytest tests/unit tests/harness tests/integration tests/contract $(CORE_COV)
	$(PY) python scripts/check_coverage.py coverage.xml
	$(PNPM) -C web test:coverage

coverage: test ## Alias for test with coverage gates

test-docker: ## The full test suite inside containers
	$(COMPOSE_TEST) up -d --wait postgres redis opensearch minio qdrant
	$(COMPOSE_TEST) --profile qdrant run --rm --build tests; rc=$$?; \
	  $(COMPOSE_TEST) --profile qdrant rm -sf tests >/dev/null 2>&1; exit $$rc

e2e: stack-ready ## Playwright end-to-end tests (with axe) against the running stack
	NODE_PATH=$(CURDIR)/web/node_modules $(PNPM) -C web exec playwright test --project=e2e

bench: stack-ready ## Performance tests with budgets
	$(PY) pytest tests/perf -q -p no:cacheprovider

# ---------------------------------------------------------------- data, AI and evals
corpus: ## Generate the corpus and questions (seed 2026)
	$(PY) crag corpus generate
	$(PY) crag corpus export-datasets

fit-reranker: ## Fit reranker weights on the dev split
	$(PY) python scripts/fit_reranker.py

reindex: ## Rebuild embeddings and both indexes
	$(COMPOSE) run --rm seed crag reindex --reembed

eval: stack-ready ## Offline evals with thresholds; writes evals/REPORT.md
	$(PY) python scripts/run_evals.py

eval-ablation: stack-ready ## Five-configuration retrieval ablation into evals/REPORT.md
	$(COMPOSE) --profile qdrant up -d --wait qdrant
	$(PY) python scripts/ablation.py

eval-live: ## Live evals with real models within LIVE_EVAL_BUDGET_USD
	$(PY) python scripts/eval_live.py

redteam: stack-ready ## Promptfoo red-team against the API, offline
	./scripts/redteam.sh

calibrate-judge: ## evalgate calibrate on the 80 labelled answers
	$(PY) evalgate calibrate --rubric evals/rubrics/answer.yaml --labels evals/datasets/judge_labels.v1.jsonl

record-fixtures: ## Record cassettes during live runs (needs provider keys)
	CRAG_RECORD_CASSETTES=1 $(PY) python scripts/eval_live.py --record

replay-failed-jobs: ## Re-enqueue failed ingestion jobs
	$(COMPOSE) exec api crag jobs replay-failed

# ---------------------------------------------------------------- gates
verify: ## lint, typecheck, security, test, e2e, eval, redteam, bench
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) security
	$(MAKE) test
	$(MAKE) e2e
	$(MAKE) eval
	$(MAKE) redteam
	$(MAKE) bench

verify-clean: ## make verify in a fresh clone in a temporary folder
	./scripts/verify_clean.sh

docs: ## Regenerate diagrams, OpenAPI, frontend types and screenshots
	$(PY) python scripts/export_openapi.py docs/openapi.json
	$(PNPM) -C web gen:api
	NODE_PATH=$(CURDIR)/web/node_modules $(PNPM) -C web exec playwright test --project=screenshots

clean: ## Remove containers, volumes, caches and build outputs
	-$(COMPOSE) --profile qdrant --profile observability --profile langfuse down -v --remove-orphans
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov coverage.xml .coverage web/dist \
	  web/coverage playwright-report test-results data/generated evals/reports/runs
