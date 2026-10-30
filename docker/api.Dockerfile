# API and Arq worker image. Multi-stage, non-root, no apt-get.
FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS build
ARG HTTPS_PROXY
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY third_party ./third_party
RUN uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
COPY data ./data
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS runtime
# the same BLAS kernels on every AVX2 host, so the seed fits the same LSA model everywhere (docs/DECISIONS.md)
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CRAG_APP_ROOT=/app OPENBLAS_CORETYPE=Haswell
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin crag
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY prompts ./prompts
COPY evals ./evals
COPY scripts ./scripts
USER 10001
EXPOSE 8610 8611
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=20 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8610/healthz', timeout=2).status == 200 else 1)"]
# with several workers (WEB_CONCURRENCY) prometheus_client keeps per-process files: start from an empty dir
CMD ["sh", "-c", "if [ -n \"$PROMETHEUS_MULTIPROC_DIR\" ]; then mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && rm -f \"$PROMETHEUS_MULTIPROC_DIR\"/*.db; fi; exec uvicorn compliance_rag.api.app:create_app --factory --host 0.0.0.0 --port 8610 --no-access-log"]
