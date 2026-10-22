#!/usr/bin/env bash
# SessionStart hook: idempotent environment setup for Claude Code on the web.
# Starts Docker with the registry mirror and installs the CLI tools the project needs.
set -u

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "session_start: not a remote session, skipping"
  exit 0
fi

log() { echo "session_start: $*"; }
PROJECT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# Docker daemon with the Docker Hub mirror
if ! docker info >/dev/null 2>&1; then
  mkdir -p /etc/docker
  [ -f /etc/docker/daemon.json ] || echo '{"registry-mirrors":["https://mirror.gcr.io"]}' > /etc/docker/daemon.json
  (nohup dockerd > /tmp/dockerd.log 2>&1 &)
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 && log "docker started" || log "docker failed to start (see /tmp/dockerd.log)"
else
  log "docker already running"
fi

# CLI tools (gitleaks, actionlint, hadolint, trivy) — idempotent
if [ -x "$PROJECT/scripts/install_tools.sh" ]; then
  "$PROJECT/scripts/install_tools.sh" >/tmp/install_tools.log 2>&1 && log "tools ready" || log "tool install failed (see /tmp/install_tools.log)"
fi

# Dependencies
if command -v uv >/dev/null 2>&1; then
  (cd "$PROJECT" && uv sync --frozen >/tmp/uv_sync.log 2>&1) && log "uv sync done" || log "uv sync failed"
fi
if command -v pnpm >/dev/null 2>&1 && [ -f "$PROJECT/web/package.json" ]; then
  (cd "$PROJECT" && pnpm -C web install --frozen-lockfile >/tmp/pnpm_install.log 2>&1) && log "pnpm install done" || log "pnpm install failed"
fi
exit 0
