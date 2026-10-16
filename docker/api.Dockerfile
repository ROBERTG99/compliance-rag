# API and Arq worker image (BUILD.md §16). Multi-stage, non-root, no apt-get.
FROM python:3.12-slim AS build
ARG HTTPS_PROXY
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY third_party ./third_party
RUN uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CRAG_APP_ROOT=/app
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin crag
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY prompts ./prompts
COPY data/generator ./data/generator
COPY data/__init__.py ./data/__init__.py
COPY evals ./evals
COPY scripts ./scripts
USER 10001
EXPOSE 8610 8611
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=20 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8610/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "compliance_rag.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8610", "--no-access-log"]
