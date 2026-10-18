"""FastAPI dependencies: app state, authenticated principal, role checks."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request

from compliance_rag.api.errors import Problem
from compliance_rag.api.state import AppState
from compliance_rag.auth.jwt import AuthError
from compliance_rag.retrieval.types import Principal


def single_valued_query(request: Request) -> None:
    """No query parameter of this API is a list: a repeated key is malformed, not "the last one wins"."""
    keys = [key for key, _ in request.query_params.multi_items()]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise Problem(
            422, "Unprocessable Content", f"repeated query parameter: {', '.join(repeated)}", "validation"
        )


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.crag
    return state


async def current_principal(request: Request, state: AppState = Depends(get_state)) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("missing bearer token")
    principal = await state.validator.principal(token.strip())
    request.state.principal = principal
    return principal


def require_role(*roles: str) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal["role"] not in roles:
            # existence of admin routes is not secret, but keep the uniform not-found shape for data
            raise Problem(403, "Forbidden", "this action needs the content admin role", "forbidden")
        return principal

    return dependency


async def ask_rate_limit(
    principal: Principal = Depends(current_principal), state: AppState = Depends(get_state)
) -> Principal:
    """30 asks per minute per user (NFR-6); 429 problem+json with Retry-After."""
    decision = await state.limiter.hit(principal["sub"])
    if not decision.allowed:
        raise Problem(
            429,
            "Too Many Requests",
            f"at most {state.limiter.per_minute} questions per minute",
            "rate_limited",
            headers={"Retry-After": str(decision.retry_after_s)},
        )
    return principal
