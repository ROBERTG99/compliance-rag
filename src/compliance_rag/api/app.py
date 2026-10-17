"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from compliance_rag import __version__
from compliance_rag.api.errors import install_error_handlers
from compliance_rag.api.openapi import install_openapi
from compliance_rag.api.routes import admin, ask, documents, evals, feedback, health
from compliance_rag.api.state import AppState, build_state
from compliance_rag.settings import Settings, get_settings


def create_app(settings: Settings | None = None, *, state: AppState | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = state is None
        app.state.crag = state or await build_state(settings)  # refuses to start on EmbedderMismatch
        if owned:
            await app.state.crag.warm_up()  # before readiness: cold caches would 503 the first asks
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
    install_openapi(app)
    app.include_router(health.router)
    app.include_router(ask.router)
    app.include_router(documents.router)
    app.include_router(admin.router)
    app.include_router(feedback.router)
    app.include_router(evals.router)
    return app
