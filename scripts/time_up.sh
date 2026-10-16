#!/usr/bin/env bash
# `make up`: start the stack with healthchecks (seed runs as a one-shot job) and time it (NFR-7: < 5 min).
set -euo pipefail
cd "$(dirname "$0")/.."
start=$(date +%s)
docker compose up -d --wait --build "$@"
elapsed=$(( $(date +%s) - start ))
mkdir -p evals/reports
printf '{"command": "docker compose up -d --wait --build", "seconds": %d, "budget_seconds": 300, "measured_at": "%s"}\n' \
  "$elapsed" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > evals/reports/time_up.json
echo "stack healthy in ${elapsed}s (budget 300s)"
if [ "$elapsed" -ge 300 ]; then echo "NFR-7 violated: make up took ${elapsed}s" >&2; exit 1; fi
