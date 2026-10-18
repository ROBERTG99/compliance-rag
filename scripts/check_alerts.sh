#!/usr/bin/env bash
# `make lint` part: promtool check and unit-test the Prometheus alert rules (BUILD.md §14).
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="$(uv run --quiet python -c "import yaml;print(yaml.safe_load(open('compose.yaml'))['services']['prometheus']['image'])")"
run() { docker run --rm --entrypoint promtool -v "$PWD/deploy/prometheus:/rules:ro" -w /rules "$IMAGE" "$@"; }
run check rules alerts.yml
run test rules alerts.test.yml
