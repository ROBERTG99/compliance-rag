"""RFC 9457 problem+json errors for every API failure."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from compliance_rag.auth.jwt import AuthError
from compliance_rag.ingest.loaders import UnsupportedDocument
from compliance_rag.ingest.pipeline import AclConflict, VersionConflict
from compliance_rag.llm.gateway import GenerationUnavailable
from compliance_rag.retrieval.hybrid import RetrievalUnavailable

PROBLEM = "application/problem+json"
log = structlog.get_logger(__name__)


class Problem(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status, self.title, self.detail, self.code = status, title, detail, code
        self.headers = headers or {}
        self.extra = extra


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    code: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://compliance-rag.example/problems/{code or status}",
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    if code:
        body["code"] = code
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


def not_found(what: str = "resource") -> Problem:
    """Unauthorized and missing resources look the same (no existence leakage)."""
    return Problem(404, "Not Found", f"{what} not found")


def allowed_methods(request: Request) -> str:
    """Every method served at this path; Starlette's own 405 lists only the first matching route's."""
    methods: set[str] = set()
    for route in request.app.router.routes:
        match, _ = route.matches({**request.scope, "method": "GET"})
        if match != Match.NONE:
            methods |= set(getattr(route, "methods", None) or ())
    return ", ".join(sorted(methods))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(
            request, exc.status, exc.title, exc.detail, exc.code, exc.headers, **exc.extra
        )

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        return problem_response(
            request, 401, "Unauthorized", str(exc), "unauthorized", headers={"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return problem_response(
            request, 422, "Unprocessable Content", "request validation failed", "validation", errors=errors
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = dict(exc.headers or {})
        if exc.status_code == 405:
            headers["Allow"] = allowed_methods(request)
        return problem_response(request, exc.status_code, str(exc.detail), None, None, headers=headers)

    @app.exception_handler(RetrievalUnavailable)
    async def _retrieval(request: Request, exc: RetrievalUnavailable) -> JSONResponse:
        return problem_response(
            request,
            503,
            "Service Unavailable",
            "retrieval is unavailable",
            "retrieval_unavailable",
            retryable=True,
        )

    @app.exception_handler(GenerationUnavailable)
    async def _generation(request: Request, exc: GenerationUnavailable) -> JSONResponse:
        return problem_response(
            request,
            503,
            "Service Unavailable",
            "generation is unavailable",
            "generation_unavailable",
            retryable=True,
        )

    @app.exception_handler(VersionConflict)
    async def _version(request: Request, exc: VersionConflict) -> JSONResponse:
        return problem_response(request, 409, "Conflict", str(exc), "version_conflict")

    @app.exception_handler(AclConflict)
    async def _acl(request: Request, exc: AclConflict) -> JSONResponse:
        return problem_response(request, 409, "Conflict", str(exc), "acl_conflict")

    @app.exception_handler(UnsupportedDocument)
    async def _unsupported(request: Request, exc: UnsupportedDocument) -> JSONResponse:
        return problem_response(request, 415, "Unsupported Media Type", str(exc), "unsupported_document")

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error_type=type(exc).__name__, path=request.url.path)
        return problem_response(request, 500, "Internal Server Error", None, "internal")
