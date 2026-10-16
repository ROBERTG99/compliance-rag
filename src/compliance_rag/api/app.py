"""FastAPI application factory."""

from fastapi import FastAPI

from compliance_rag import __version__
from compliance_rag.api.routes import ask, health


def create_app() -> FastAPI:
    app = FastAPI(title="compliance-rag", version=__version__)
    app.include_router(health.router)
    app.include_router(ask.router)
    return app
