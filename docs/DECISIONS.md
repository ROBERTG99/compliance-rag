# Decisions log

Format: date · decision · alternatives considered · reason. Architectural decisions also have an ADR in `docs/adr/`.

| Date | Decision | Alternatives | Reason |
|---|---|---|---|
| 2026-10-16 | The `.claude/settings.json` and `.claude/rules/git-commits.md` files were not pre-seeded, so they were created and committed alone as `chore: configure commit attribution` (§1.1 step 4). | Treat as pre-seeded | They did not exist in the initial commit. |
| 2026-10-16 | Implement the used evalgate subset in `third_party/evalgate/` (suite loader, metrics, report v1, `check`, `report`, `calibrate`, `FakeJudge`). | Depend on `git+https://github.com/ROBERTG99/evalgate@v0.1.0` | `git ls-remote` shows the repository exists but has no `v0.1.0` tag (only `main` with a spec). The switch is listed under "Needs the maintainer". |
| 2026-10-16 | OpenSearch image `opensearchproject/opensearch:2.19.1` pulled through the Docker Hub mirror (`mirror.gcr.io`). | `public.ecr.aws/opensearchproject/opensearch` | ECR Public blob downloads (CloudFront) return 403 behind the cloud proxy; the mirror serves the same official image. |
| 2026-10-16 | Use Python 3.12 (`.python-version`) for the host venv as well as images. | Host Python 3.13 | One interpreter everywhere matches `python:3.12-slim` in the images. |
| 2026-10-16 | Hooks were registered in `.claude/settings.json` before their scripts existed; the missing PreToolUse script blocked every Bash/Write/Edit call. With the maintainer's go-ahead, placeholder scripts were created first, then replaced by the real hooks in T-05. A never-do line in `CLAUDE.md` now records the lesson. | Remove the hooks block | Settings reload live in the session; creating the scripts was the minimal fix. |
