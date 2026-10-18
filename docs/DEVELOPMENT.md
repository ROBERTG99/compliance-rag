# Development

## Environment recorded at bootstrap (2026-10-16)

Environment: Claude Code on the web (`CLAUDE_CODE_REMOTE=true`), Appendix A applied.

| Tool | Version |
|---|---|
| uname | `Linux vm 6.18.44-fc-v139 #1 SMP PREEMPT_DYNAMIC @0 x86_64 x86_64 x86_64 GNU/Linux` |
| python3 (system) | Python 3.13.16 |
| python (project venv) | Python 3.12.13 (uv-managed) |
| uv | uv 0.11.32 (x86_64-unknown-linux-gnu) |
| node | v22.22.0 |
| pnpm | 10.28.0 |
| docker | Docker version 29.8.2, build 7fc2dff |
| docker compose | Docker Compose version v5.6.0 |
| git | git version 2.43.0 |
| go | go version go1.24.7 linux/amd64 |

## Setup

```bash
make bootstrap     # uv sync, pnpm install, .env from .env.example
make check-fast    # ruff + mypy + unit tests (< 60 s)
make up            # full stack in Docker Compose
make seed          # synthetic corpus (seed 2026)
```

See `CONTRIBUTING.md` for the workflow and `docs/runbook.md` for operations.

## Signing in locally

The SPA (<http://localhost:8600>) signs in with authorization code + PKCE against the dev OIDC issuer
(<http://localhost:8612>), which lists four synthetic personas: analyst, legal, support and content
admin. The "Persona (dev)" select in the header switches identity without the redirect by calling
dev-oidc's `/dev/token` through the same-origin `/oidc/` proxy.

The switcher is compiled in only for `vite dev`, the unit tests and builds with
`VITE_DEV_PERSONAS=1`. The compose `web` service passes `VITE_DEV_PERSONAS=1` because the whole
stack is local; the Dockerfile default is `0`, so any other build has no switcher.
