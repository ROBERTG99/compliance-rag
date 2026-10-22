# MinIO built from source: the official image is not reachable from the build environment
# (Docker Hub mirror has no minio/minio, quay.io is blocked). See docs/DECISIONS.md.
# Dev-only S3 stand-in. The last source release is rebuilt with a current Go toolchain and current
# golang.org/x modules so the binary does not carry their published vulnerabilities.
FROM golang:1.27.3@sha256:f20d83a83e18dbd2a4714b8ffd4b30b287b6243962dd75608e86abcc63ba4efc AS build
ARG HTTPS_PROXY
ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ENV CGO_ENABLED=0 GOFLAGS=-trimpath GOTOOLCHAIN=local
WORKDIR /src
RUN go mod init minio-build \
 && go get "github.com/minio/minio@${MINIO_VERSION}" \
 && go get golang.org/x/crypto@v0.57.0 golang.org/x/net@v0.60.0 \
      google.golang.org/grpc@v1.83.2 github.com/rabbitmq/amqp091-go@v1.13.0 go.opentelemetry.io/otel/sdk@v1.44.0 \
      github.com/go-jose/go-jose/v4@v4.1.4 github.com/buger/jsonparser@v1.1.2 github.com/apache/thrift@v0.24.0 github.com/prometheus/prometheus@v0.311.3 github.com/klauspost/compress@v1.18.7 \
 && go build -mod=mod -o /go/bin/minio github.com/minio/minio

FROM alpine:3.22.6@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN adduser -D -u 10001 minio && mkdir -p /data && chown minio /data
COPY --from=build /go/bin/minio /usr/local/bin/minio
USER 10001
EXPOSE 9000 9001
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD wget -qO- http://127.0.0.1:9000/minio/health/live >/dev/null || exit 1
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
