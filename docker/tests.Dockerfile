# Test runner for `make test-docker` (compose.test.yaml): dev dependencies only; the repository is mounted
# read-only at /repo, so the image never needs rebuilding for a code change.
FROM python:3.14.7-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ARG HTTPS_PROXY
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_SYNC=1 UV_FROZEN=1 \
    PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/repo/src:/repo/third_party/evalgate/src:/repo PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_CORETYPE=Haswell
RUN pip install --no-cache-dir uv==0.11.32 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin tester
WORKDIR /deps
COPY pyproject.toml uv.lock README.md ./
COPY third_party ./third_party
RUN uv sync --frozen --no-install-project --no-editable
USER 10001
WORKDIR /repo
CMD ["pytest", "--help"]
