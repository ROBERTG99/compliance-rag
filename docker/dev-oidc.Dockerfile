# Development-only OIDC issuer with synthetic personas. Never deploy.
FROM python:3.14.7-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS build
ARG HTTPS_PROXY
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
COPY apps/dev-oidc/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.14.7-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 DEV_OIDC_PUBLIC_URL=http://localhost:8612
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin oidc
COPY --from=build /opt/venv /opt/venv
COPY apps/dev-oidc/dev_oidc /app/dev_oidc
WORKDIR /app
USER 10001
EXPOSE 8612
HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8612/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "dev_oidc.app:app", "--host", "0.0.0.0", "--port", "8612", "--no-access-log"]
