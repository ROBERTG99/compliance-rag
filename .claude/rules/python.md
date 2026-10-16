---
paths: ["src/**/*.py", "tests/**/*.py", "scripts/**/*.py", "data/**/*.py", "apps/**/*.py", "migrations/**/*.py"]
---
# Python

- Python 3.12, `uv` only (`uv add`, `uv run`); never `pip install` into the venv.
- `mypy --strict` must stay clean on `src/`; no `# type: ignore` without an error code and a reason.
- Async all the way in API, graph and retrieval code; never block the event loop (wrap CPU-heavy calls in `asyncio.to_thread`).
- Settings come from `compliance_rag.settings.Settings` (`CRAG_` prefix); never read `os.environ` elsewhere in `src/`.
- Errors leaving the API are RFC 9457 problem+json built in `api/errors.py`.
- Logging through `structlog` (`compliance_rag.obs.logging`); never log chunk text or question text.
