#!/usr/bin/env bash
# Format, run `make check-fast`, and commit everything only when it is green.
# Usage: scripts/task_commit.sh "<conventional commit message>"
set -euo pipefail
cd "$(dirname "$0")/.."
msg="$1"
uv run ruff check --fix -q src tests scripts data apps third_party migrations >/dev/null 2>&1 || true
uv run ruff format -q src tests scripts data apps third_party migrations 2>/dev/null || true
if ! make check-fast > /tmp/check-fast.log 2>&1; then
  echo "check-fast FAILED; not committing. Last lines:" >&2
  tail -25 /tmp/check-fast.log >&2
  exit 1
fi
git add -A
git commit -q -m "$msg"
echo "committed: $(git log -1 --format='%h %s')"
