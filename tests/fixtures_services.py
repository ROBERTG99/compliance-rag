"""Service fixtures for integration tests.

Each service comes from a ``CRAG_TEST_*`` URL when set (inside ``compose.test.yaml``) or from a
testcontainers container started once per session. Postgres gives every test module a fresh
database migrated to head; OpenSearch gives every test its own index name.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest


def _compose_image(service: str) -> str:
    """Testcontainers use exactly the images pinned in compose.yaml (one source of truth)."""
    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")
    )
    return str(compose["services"][service]["image"])


PG_IMAGE = _compose_image("postgres")
REDIS_IMAGE = _compose_image("redis")
OPENSEARCH_IMAGE = _compose_image("opensearch")
MINIO_IMAGE = _compose_image("minio")
QDRANT_IMAGE = _compose_image("qdrant")


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
            "cluster.routing.allocation.disk.threshold_enabled": "false",
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


@pytest.fixture(scope="session")
def lsa_embedder():  # type: ignore[no-untyped-def]
    from compliance_rag.embed.lsa import LocalLSAEmbedder
    from data.generator.corpus import SEED, build_corpus

    texts = [
        a.heading + "\n" + "\n".join(a.paragraphs)
        for p in build_corpus(SEED)[:80]
        for a in p.current.articles
    ]
    return LocalLSAEmbedder(dim=384, seed=2026).fit(texts)


@pytest.fixture
async def ingest_deps(
    migrated_db: Database, s3_config: S3Config, opensearch_url: str, os_index: str, lsa_embedder
):  # type: ignore[no-untyped-def]
    from compliance_rag.db.pool import create_pool
    from compliance_rag.ingest.objectstore import S3ObjectStore
    from compliance_rag.ingest.pipeline import IngestDeps
    from compliance_rag.retrieval.bm25 import BM25Index

    pool = await create_pool(migrated_db.url, min_size=1, max_size=6)
    objects = S3ObjectStore(
        s3_config.endpoint_url,
        s3_config.access_key,
        s3_config.secret_key,
        bucket=f"crag-test-{uuid.uuid4().hex[:8]}",
    )
    await objects.ensure_bucket()
    bm25 = BM25Index(opensearch_url, index=os_index, alias=f"{os_index}-alias")
    await bm25.init()
    deps = IngestDeps(pool=pool, objects=objects, bm25=bm25, embedder=lsa_embedder)
    try:
        yield deps
    finally:
        await bm25.drop()
        await bm25.close()
        await pool.close()


# ----------------------------------------------------------------------------- API environment
API_DOCS = {"KYC-0042", "AML-0107", "CMP-0215"}


def _api_document_ids() -> set[str]:
    import json
    from pathlib import Path

    rows = [
        json.loads(line)
        for line in (Path(__file__).resolve().parents[1] / "evals/datasets/questions.v1.jsonl")
        .read_text()
        .splitlines()
    ]
    dev = [r for r in rows if r["split"] == "dev" and r["meta"]["category"] in {"single_hop", "acl_probe"}][
        :24
    ]
    return API_DOCS | {g["document_id"] for r in dev for g in r["meta"]["gold"]}


@dataclass
class ApiEnv:
    app: Any
    settings: Any
    oidc: Any

    async def token(self, persona: str) -> str:
        resp = await self.oidc.post("/dev/token", json={"persona": persona})
        return str(resp.json()["access_token"])

    async def client(self, persona: str | None = None) -> Any:
        import httpx

        headers = {"Authorization": f"Bearer {await self.token(persona)}"} if persona else {}
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://api", headers=headers
        )


@asynccontextmanager
async def make_api_env(
    pg_admin_url: str,
    redis_url: str,
    opensearch_url: str,
    s3_config: S3Config,
    only: set[str] | None = None,
) -> AsyncIterator[ApiEnv]:
    """A migrated database, its own index and bucket, the seeded subset and an in-process dev-oidc."""
    import sys
    from pathlib import Path

    import httpx

    from compliance_rag.api.app import create_app
    from compliance_rag.api.state import build_state
    from compliance_rag.auth.jwt import JWKSCache, TokenValidator
    from compliance_rag.db.migrate import upgrade
    from compliance_rag.ingest.seed import seed_corpus
    from compliance_rag.settings import Settings

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "dev-oidc"))
    from dev_oidc.app import create_app as create_oidc

    db = _create_database(pg_admin_url)
    upgrade(db.url)
    suffix = uuid.uuid4().hex[:8]
    settings = Settings(
        _env_file=None,
        database_url=db.url,
        redis_url=redis_url,
        opensearch_url=opensearch_url,
        opensearch_index=f"crag-api-{suffix}",
        opensearch_alias=f"crag-api-{suffix}-alias",
        s3_endpoint_url=s3_config.endpoint_url,
        s3_access_key=s3_config.access_key,
        s3_secret_key=s3_config.secret_key,
        s3_bucket=f"crag-api-{suffix}",
        oidc_issuer="http://localhost:8612",
        oidc_public_issuer="http://localhost:8612",
        rate_limit_per_min=100_000,  # the shared session app; test_limits swaps in a 30/min limiter
    )
    oidc_app = create_oidc(public_url="http://localhost:8612")
    oidc = httpx.AsyncClient(transport=httpx.ASGITransport(app=oidc_app), base_url="http://localhost:8612")
    validator = TokenValidator(
        "http://localhost:8612", "compliance-rag", JWKSCache("http://localhost:8612", client=oidc)
    )
    state = await build_state(settings, validator=validator)
    await state.services.objects.ensure_bucket()
    await state.services.bm25.init()
    await seed_corpus(
        state.services.ingest_deps(),
        only=only if only is not None else _api_document_ids(),
        log=lambda _m: None,
    )
    await state.reload()
    app = create_app(settings, state=state)
    try:
        yield ApiEnv(app=app, settings=settings, oidc=oidc)
    finally:
        await state.close()
        await oidc.aclose()
        _drop_database(pg_admin_url, db)


@pytest.fixture(scope="session")
async def api_env(
    pg_admin_url: str, redis_url: str, opensearch_url: str, s3_config: S3Config
) -> AsyncIterator[ApiEnv]:
    async with make_api_env(pg_admin_url, redis_url, opensearch_url, s3_config) as env:
        yield env
