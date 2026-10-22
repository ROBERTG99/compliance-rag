#!/usr/bin/env bash
# `make verify-clean`: `make verify` in a fresh clone of the committed HEAD, with no provider
# keys and its own compose project (fresh volumes). The dev stack must be down first: the ports are shared.
set -euo pipefail
VERIFY_OUT="${VERIFY_OUT:+$(realpath -m "$VERIFY_OUT")}"  # resolved against the caller's directory
cd "$(dirname "$0")/.."
if curl -sf -o /dev/null --max-time 2 http://localhost:8610/healthz; then
  echo "the dev stack is running on the shared ports: run \`make down\` first" >&2
  exit 2
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/crag-verify.XXXXXX")"
# tear down everything the run started, test container and profiles included (as `make down` does)
trap 'cd /; (cd "$WORK/compliance-rag" 2>/dev/null && docker compose -f compose.yaml -f compose.test.yaml \
  --profile qdrant --profile observability --profile langfuse down -v --remove-orphans >/dev/null 2>&1) || true; \
  rm -rf "$WORK"' EXIT
git clone --quiet --no-hardlinks "$PWD" "$WORK/compliance-rag"
cd "$WORK/compliance-rag"
echo "fresh clone of $(git rev-parse --short HEAD) in $WORK"
export COMPOSE_PROJECT_NAME=crag-verify
unset ANTHROPIC_API_KEY OPENAI_API_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
# each step timed: `== <step>: <seconds>s rc=<code>` lines are the lines to compare between runs
step() {
  local name="$1" start rc
  shift
  start=$(date +%s)
  echo "== ${name}: started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  set +e
  "$@"
  rc=$?
  set -e
  echo "== ${name}: $(( $(date +%s) - start ))s rc=${rc}"
  return "$rc"
}
step bootstrap make bootstrap
step up make up
step verify make verify
# in the same clone: the scripted demo and every suite inside containers
step demo make demo
step test-docker make test-docker
if [ -n "${VERIFY_OUT:-}" ]; then  # keep the clone's generated reports
  mkdir -p "$VERIFY_OUT" && cp -r evals/REPORT.md evals/reports "$VERIFY_OUT/"
fi
echo "verify-clean: make verify, make demo and make test-docker passed in a fresh clone with no API keys"
