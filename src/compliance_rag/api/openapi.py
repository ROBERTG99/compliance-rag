"""OpenAPI post-processing: bearer security, RFC 9457 error responses per route (§4.4)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from compliance_rag.api.errors import PROBLEM
from compliance_rag.api.schemas import Problem

_DESCRIPTIONS = {
    400: "Malformed request body",
    401: "Missing or invalid bearer token",
    403: "Role not allowed (admin routes only)",
    404: "Not found or not authorized (indistinguishable)",
    409: "Version or ACL conflict",
    413: "Body too large (uploads 20 MB, JSON 1 MiB)",
    415: "Unsupported or mismatched file type",
    422: "Validation error",
    429: "Rate limit exceeded (30 asks per minute per user)",
    503: "Dependency unavailable",
}

# documented error statuses per operation (§4.4 plus 401 on every /v1 route and 403 on admin routes)
ERRORS: dict[tuple[str, str], list[int]] = {
    ("post", "/v1/ask"): [401, 404, 422, 429, 503],
    ("get", "/v1/runs/{run_id}/events"): [401, 404, 422],
    ("get", "/v1/runs/{run_id}"): [401, 404, 422],
    ("post", "/v1/documents"): [401, 403, 409, 413, 415, 422, 503],
    ("post", "/v1/documents:from-s3"): [401, 403, 404, 409, 413, 415, 422, 503],
    ("get", "/v1/documents"): [401, 422],
    ("get", "/v1/documents/{document_id}"): [401, 404, 422],
    ("get", "/v1/chunks/{chunk_id}"): [401, 404, 422],
    ("put", "/v1/documents/{document_id}/acl"): [401, 403, 404, 409, 422],
    ("get", "/v1/ingestion-jobs"): [401, 403, 422],
    ("get", "/v1/index/lag"): [401, 403],
    ("post", "/v1/feedback"): [401, 404, 422],
    ("get", "/v1/feedback"): [401, 403, 422, 503],
    ("patch", "/v1/feedback/{feedback_id}"): [401, 403, 404, 422, 503],
    ("get", "/v1/evals/latest"): [401, 404],
    ("get", "/v1/me"): [401],
}

_HEADERS: dict[int, dict[str, Any]] = {
    401: {"WWW-Authenticate": {"schema": {"type": "string"}, "description": "Bearer challenge"}},
    429: {"Retry-After": {"schema": {"type": "integer", "minimum": 1}, "description": "Seconds to wait"}},
}


def _problem_response(status: int) -> dict[str, Any]:
    response: dict[str, Any] = {
        "description": _DESCRIPTIONS[status],
        "content": {PROBLEM: {"schema": {"$ref": "#/components/schemas/Problem"}}},
    }
    if status in _HEADERS:
        response["headers"] = _HEADERS[status]
    return response


def build_openapi(app: FastAPI) -> dict[str, Any]:
    spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    components = spec.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)
    schemas["Problem"] = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
    components["securitySchemes"] = {
        "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            responses: dict[str, Any] = op.setdefault("responses", {})
            responses.pop("422", None)  # FastAPI's default is not the problem+json body we send
            if path.startswith("/v1/"):
                op["security"] = [{"bearerAuth": []}]
            statuses = list(ERRORS.get((method, path), [401, 422] if path.startswith("/v1/") else []))
            if "requestBody" in op:
                statuses += [400, 413]  # undecodable or oversized bodies are rejected before validation
            for status in sorted(set(statuses)):
                responses[str(status)] = _problem_response(status)
    return spec


def install_openapi(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented override hook
