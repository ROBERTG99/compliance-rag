#!/usr/bin/env bash
# Installs the security/lint CLIs into ~/.local/bin, idempotently.
# gitleaks and actionlint via `go install`; hadolint and trivy from GitHub release binaries.
set -euo pipefail
BIN="${CRAG_TOOLS_BIN:-$HOME/.local/bin}"
mkdir -p "$BIN"
export PATH="$BIN:$PATH"
GITLEAKS_VERSION="v8.30.1"
ACTIONLINT_VERSION="v1.7.12"
HADOLINT_VERSION="v2.15.1"
TRIVY_VERSION="0.76.0"
OS="$(uname -s)"; ARCH="$(uname -m)"

have() { command -v "$1" >/dev/null 2>&1; }

if ! have gitleaks; then
  if [ "$OS" = "Darwin" ] && have brew; then brew install gitleaks; else
    GOBIN="$BIN" go install "github.com/zricethezav/gitleaks/v8@${GITLEAKS_VERSION}"; fi
fi
if ! have actionlint; then
  if [ "$OS" = "Darwin" ] && have brew; then brew install actionlint; else
    GOBIN="$BIN" go install "github.com/rhysd/actionlint/cmd/actionlint@${ACTIONLINT_VERSION}"; fi
fi
if ! have hadolint; then
  if [ "$OS" = "Darwin" ] && have brew; then brew install hadolint; else
    case "$ARCH" in x86_64) HA=x86_64 ;; aarch64|arm64) HA=arm64 ;; *) HA="$ARCH" ;; esac
    curl -fsSL -o "$BIN/hadolint" "https://github.com/hadolint/hadolint/releases/download/${HADOLINT_VERSION}/hadolint-Linux-${HA}"
    chmod +x "$BIN/hadolint"
  fi
fi
if ! have trivy; then
  if [ "$OS" = "Darwin" ] && have brew; then brew install trivy; else
    case "$ARCH" in x86_64) TA=64bit ;; aarch64|arm64) TA=ARM64 ;; *) TA="$ARCH" ;; esac
    tmp="$(mktemp -d)"
    curl -fsSL -o "$tmp/trivy.tgz" "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TA}.tar.gz"
    tar -xzf "$tmp/trivy.tgz" -C "$tmp" trivy && mv "$tmp/trivy" "$BIN/trivy" && rm -rf "$tmp"
  fi
fi
for t in gitleaks actionlint hadolint trivy; do
  printf '%-10s %s\n' "$t" "$($t --version 2>&1 | head -1)"
done
