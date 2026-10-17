#!/usr/bin/env bash
# `make security` (BUILD.md §12): gitleaks, bandit, pip-audit, pnpm audit, hadolint, actionlint, licences and
# trivy on the built images. Every step runs; the script fails if any step fails. Accepted findings are listed
# with reasons in docs/security.md (pnpm `auditConfig.ignoreGhsas`, `.trivyignore`).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
TRIVY_DB="${TRIVY_DB_REPOSITORY:-mirror.gcr.io/aquasec/trivy-db}"
IMAGES=(compliance-rag/api:dev compliance-rag/web:dev compliance-rag/dev-oidc:dev "$(docker compose config --images 2>/dev/null | grep compliance-rag/minio | head -1)")
failed=()

step() {
  local name="$1"; shift
  echo "== $name"
  if "$@"; then echo "   ok"; else echo "   FAILED"; failed+=("$name"); fi
}

step gitleaks gitleaks git --no-banner --redact --log-level warn .
# medium findings are reviewed in docs/security.md (B608: constant SQL fragments, values bound as parameters)
step bandit uv run bandit -q -r src apps -c pyproject.toml --severity-level high
# the project itself and the vendored evalgate are editable installs (not on PyPI); everything else is audited
step pip-audit uv run pip-audit --skip-editable --progress-spinner off
step pnpm-audit-web pnpm -C web audit --audit-level high
step pnpm-audit-redteam pnpm -C evals/redteam audit --audit-level high
step hadolint hadolint docker/*.Dockerfile
if compgen -G ".github/workflows/*.yml" >/dev/null; then step actionlint actionlint; fi
step licences uv run python scripts/check_licences.py
if [ "${SKIP_TRIVY:-0}" = "1" ] || ! docker info >/dev/null 2>&1; then
  echo "== trivy skipped (no Docker daemon or SKIP_TRIVY=1)"
else
  for image in "${IMAGES[@]}"; do
    [ -n "$image" ] || continue
    if docker image inspect "$image" >/dev/null 2>&1; then
      step "trivy $image" trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
        --ignorefile .trivyignore --db-repository "$TRIVY_DB" --exit-code 1 "$image"
    else
      echo "== trivy $image: not built (run docker compose build)"; failed+=("trivy $image (missing)")
    fi
  done
fi

if [ ${#failed[@]} -gt 0 ]; then
  printf 'security: %d step(s) failed: %s\n' "${#failed[@]}" "${failed[*]}"
  exit 1
fi
echo "security: all checks passed"
