"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from compliance_rag import __version__
from compliance_rag.api.correlation import CorrelationId
from compliance_rag.api.errors import install_error_handlers
from compliance_rag.api.limits import BodyLimit
from compliance_rag.api.openapi import install_openapi
from compliance_rag.api.routes import admin, ask, documents, evals, feedback, health
from compliance_rag.api.state import AppState, build_state
from compliance_rag.obs.logging import configure_logging
from compliance_rag.obs.tracing import instrument_app, instrument_libraries, setup_tracing
from compliance_rag.settings import Settings, get_settings

log = structlog.get_logger(__name__)
WARM_UP_TIMEOUT_S = 60.0


def create_app(settings: Settings | None = None, *, state: AppState | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, service="api")
    setup_tracing("api", settings.otel_exporter_otlp_endpoint)
    instrument_libraries()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = state is None
        app.state.crag = state or await build_state(settings)  # refuses to start on EmbedderMismatch
        if owned:
            # before readiness: cold caches would 503 the first asks; bounded so a hung store cannot block start-up
            try:
                await asyncio.wait_for(app.state.crag.warm_up(), timeout=WARM_UP_TIMEOUT_S)
            except TimeoutError:
                log.warning("warm_up_timeout", seconds=WARM_UP_TIMEOUT_S)
        try:
            yield
        finally:
            if owned:
                await app.state.crag.close()

    app = FastAPI(
        title="compliance-rag",
        version=__version__,
        lifespan=lifespan,
        description="Compliance policy Q&A with verified citations, ACL and version validity.",
    )
    if state is not None:
        app.state.crag = state  # tests drive the app without running the lifespan
    install_error_handlers(app)
    # 1 MiB for JSON bodies; uploads get the configured limit plus room for the multipart envelope
    app.add_middleware(
        BodyLimit,
        default_limit=1024 * 1024,
        limits={"/v1/documents": settings.max_upload_bytes + 64 * 1024},
    )
    app.add_middleware(CorrelationId)  # outermost: every log line of the request carries the id
    install_openapi(app)
    instrument_app(app)
    app.include_router(health.router)
    app.include_router(ask.router)
    app.include_router(documents.router)
    app.include_router(admin.router)
    app.include_router(feedback.router)
    app.include_router(evals.router)
    return app
