# MinIO built from source: the official image is not reachable from the build environment
# (Docker Hub mirror has no minio/minio, quay.io is blocked). See docs/DECISIONS.md.
FROM golang:1.24 AS build
ARG HTTPS_PROXY
ARG MINIO_VERSION=RELEASE.2025-04-22T22-12-26Z
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
RUN go install "github.com/minio/minio@${MINIO_VERSION}"

FROM alpine:3.20
RUN adduser -D -u 10001 minio && mkdir -p /data && chown minio /data
COPY --from=build /go/bin/minio /usr/local/bin/minio
USER 10001
EXPOSE 9000 9001
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD wget -qO- http://127.0.0.1:9000/minio/health/live >/dev/null || exit 1
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
