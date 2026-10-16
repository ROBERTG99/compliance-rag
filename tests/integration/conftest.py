"""Service fixtures for integration tests.

Each service comes from a ``CRAG_TEST_*`` URL when set (inside ``compose.test.yaml``) or from a
testcontainers container started once per session. Postgres gives every test module a fresh
database migrated to head; OpenSearch gives every test its own index name.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import psycopg
import pytest

pytestmark = pytest.mark.integration

PG_IMAGE = "pgvector/pgvector:pg16"
REDIS_IMAGE = "redis:7-alpine"
OPENSEARCH_IMAGE = "opensearchproject/opensearch:2.19.1"
MINIO_IMAGE = "compliance-rag/minio:RELEASE.2025-04-22T22-12-26Z"
QDRANT_IMAGE = "qdrant/qdrant:latest"


def _docker_container(image: str, port: int, env: dict[str, str] | None = None, command: str | None = None):  # type: ignore[no-untyped-def]
    from testcontainers.core.container import DockerContainer

    container = DockerContainer(image).with_exposed_ports(port)
    for key, value in (env or {}).items():
        container = container.with_env(key, value)
    if command:
        container = container.with_command(command)
    return container


def _wait_http(url: str, timeout_s: float = 120.0) -> None:
    import time

    import httpx

    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return
        except Exception as exc:
            last = exc
        time.sleep(0.5)
    raise TimeoutError(f"{url} not ready: {last}")


@pytest.fixture(scope="session")
def pg_admin_url() -> Iterator[str]:
    url = os.environ.get("CRAG_TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(PG_IMAGE, username="crag", password="crag", dbname="crag", driver=None) as pg:
        yield pg.get_connection_url()


@dataclass
class Database:
    url: str
    name: str


def _create_database(admin_url: str) -> Database:
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_url.rpartition("/")
    return Database(url=f"{base}/{name}", name=name)


def _drop_database(admin_url: str, db: Database) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)')


@pytest.fixture
def empty_db(pg_admin_url: str) -> Iterator[Database]:
    db = _create_database(pg_admin_url)
    try:
        yield db
    finally:
        _drop_database(pg_admin_url, db)


@pytest.fixture
def migrated_db(empty_db: Database) -> Database:
    from compliance_rag.db.migrate import upgrade

    upgrade(empty_db.url)
    return empty_db


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    url = os.environ.get("CRAG_TEST_REDIS_URL")
    if url:
        yield url
        return
    container = _docker_container(REDIS_IMAGE, 6379)
    with container:
        from testcontainers.core.waiting_utils import wait_for_logs

        wait_for_logs(container, "Ready to accept connections", timeout=60)
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def opensearch_url() -> Iterator[str]:
    url = os.environ.get("CRAG_TEST_OPENSEARCH_URL")
    if url:
        yield url
        return
    container = _docker_container(
        OPENSEARCH_IMAGE,
        9200,
        env={
            "discovery.type": "single-node",
            "DISABLE_SECURITY_PLUGIN": "true",
            "DISABLE_INSTALL_DEMO_CONFIG": "true",
            "OPENSEARCH_JAVA_OPTS": "-Xms512m -Xmx512m",
        },
    )
    with container:
        base = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9200)}"
        _wait_http(f"{base}/_cluster/health?wait_for_status=yellow&timeout=1s", timeout_s=180)
        yield base


@pytest.fixture
def os_index() -> str:
    return f"crag-test-{uuid.uuid4().hex[:10]}"


@dataclass
class S3Config:
    endpoint_url: str
    access_key: str
    secret_key: str


@pytest.fixture(scope="session")
def s3_config() -> Iterator[S3Config]:
    url = os.environ.get("CRAG_TEST_S3_ENDPOINT_URL")
    if url:
        yield S3Config(
            url,
            os.environ.get("CRAG_TEST_S3_ACCESS_KEY", "crag-dev-access"),
            os.environ.get("CRAG_TEST_S3_SECRET_KEY", "crag-dev-secret-key"),
        )
        return
    container = _docker_container(
        MINIO_IMAGE,
        9000,
        env={"MINIO_ROOT_USER": "crag-test-access", "MINIO_ROOT_PASSWORD": "crag-test-secret-key"},
        command="server /data",
    )
    with container:
        base = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
        _wait_http(f"{base}/minio/health/live")
        yield S3Config(base, "crag-test-access", "crag-test-secret-key")


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    url = os.environ.get("CRAG_TEST_QDRANT_URL")
    if url:
        yield url
        return
    container = _docker_container(QDRANT_IMAGE, 6333)
    with container:
        base = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(6333)}"
        _wait_http(f"{base}/readyz")
        yield base


@pytest.fixture
async def aconn(migrated_db: Database) -> AsyncIterator[psycopg.AsyncConnection]:  # type: ignore[type-arg]
    conn = await psycopg.AsyncConnection.connect(migrated_db.url, autocommit=True)
    try:
        yield conn
    finally:
        await conn.close()
