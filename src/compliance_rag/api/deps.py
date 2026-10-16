"""FastAPI dependencies: app state, authenticated principal, role checks."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request

from compliance_rag.api.errors import Problem
from compliance_rag.api.state import AppState
from compliance_rag.auth.jwt import AuthError
from compliance_rag.retrieval.types import Principal


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
