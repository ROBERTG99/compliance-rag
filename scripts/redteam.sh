#!/usr/bin/env bash
# `make redteam`: Promptfoo red-team (evals/redteam) against the running API, offline. Exits non-zero on any
# failing case and writes a summary to evals/reports/redteam.json for evals/REPORT.md.
set -euo pipefail
cd "$(dirname "$0")/.."
API="${API_URL:-http://localhost:8610}"
OIDC="${OIDC_URL:-http://localhost:8612}"
RUNS=evals/reports/runs
mkdir -p "$RUNS"

for persona in analyst legal support admin; do
  token=$(curl -sf -X POST "$OIDC/dev/token" -H 'Content-Type: application/json' \
    -d "{\"persona\":\"$persona\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
  export "CRAG_TOKEN_${persona^^}=$token"
done
export CRAG_REDTEAM_API="$API"
export PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 PROMPTFOO_DISABLE_SHARING=1
export PROMPTFOO_CONFIG_DIR="$PWD/$RUNS/promptfoo"

pnpm -C evals/redteam install --frozen-lockfile --silent
rc=0
pnpm -C evals/redteam exec promptfoo eval -c promptfooconfig.yaml --no-cache --no-progress-bar \
  -o "$PWD/$RUNS/redteam.json" || rc=$?
uv run python scripts/redteam_summary.py "$RUNS/redteam.json" || rc=$?
exit $rc
