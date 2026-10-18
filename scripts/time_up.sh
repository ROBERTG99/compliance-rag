#!/usr/bin/env bash
# `make up`: start the stack with healthchecks (seed runs as a one-shot job) and time it (NFR-7: < 5 min).
set -euo pipefail
cd "$(dirname "$0")/.."
start=$(date +%s)
if ! docker compose up -d --wait --build "$@"; then
  # leave evidence before anything tears the stack down: states, then the logs of every service not running
  docker compose ps -a
  for svc in $(docker compose ps -a --format '{{.Service}} {{.State}}' | awk '$2 != "running" {print $1}'); do
    echo "---- logs: $svc"
    docker compose logs --tail 80 "$svc"
  done
  exit 1
fi
elapsed=$(( $(date +%s) - start ))
mkdir -p evals/reports
printf '{"command": "docker compose up -d --wait --build", "seconds": %d, "budget_seconds": 300, "measured_at": "%s"}\n' \
  "$elapsed" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > evals/reports/time_up.json
echo "stack healthy in ${elapsed}s (budget 300s)"
if [ "$elapsed" -ge 300 ]; then echo "NFR-7 violated: make up took ${elapsed}s" >&2; exit 1; fi
