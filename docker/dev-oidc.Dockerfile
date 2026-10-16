# Development-only OIDC issuer with synthetic personas (BUILD.md §4.1). Never deploy.
FROM python:3.12-slim AS build
ARG HTTPS_PROXY
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
COPY apps/dev-oidc/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim
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
