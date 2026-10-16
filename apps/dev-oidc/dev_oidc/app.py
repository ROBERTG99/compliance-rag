"""Dev OIDC issuer (BUILD.md §4.1): authorization code + PKCE (S256) for the SPA and a direct
``/dev/token`` shortcut for scripts and tests. RS256 keys are generated at start-up and published at
``/jwks.json``. Personas: analyst, legal, support and admin @northwind.test (synthetic)."""

from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

AUDIENCE = "compliance-rag"
ROLE_GROUPS = {
    "analyst": ["compliance", "all"],
    "legal": ["legal", "compliance", "all"],
    "support": ["support", "all"],
    "content_admin": ["compliance", "all"],
}
PERSONAS = {
    "analyst": {"sub": "analyst@northwind.test", "name": "Avery Analyst", "role": "analyst"},
    "legal": {"sub": "legal@northwind.test", "name": "Lee Legal", "role": "legal"},
    "support": {"sub": "support@northwind.test", "name": "Sam Support", "role": "support"},
    "admin": {"sub": "admin@northwind.test", "name": "Ada Admin", "role": "content_admin"},
}
CODE_TTL_S = 120


@dataclass
class PendingCode:
    persona: str
    client_id: str
    redirect_uri: str
    challenge: str
    expires: float


class DevTokenRequest(BaseModel):
    persona: str
    audience: str = AUDIENCE
    ttl_s: int = 3600
    groups: list[str] | None = None


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def create_app(public_url: str | None = None) -> FastAPI:
    issuer = (public_url or os.environ.get("DEV_OIDC_PUBLIC_URL", "http://localhost:8612")).rstrip("/")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    kid = hashlib.sha256(_b64(numbers.n).encode()).hexdigest()[:16]
    jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": _b64(numbers.n), "e": _b64(numbers.e)}
    codes: dict[str, PendingCode] = {}
    app = FastAPI(title="dev-oidc", docs_url=None, redoc_url=None)

    def mint(
        persona: str, audience: str = AUDIENCE, ttl_s: int = 3600, groups: list[str] | None = None
    ) -> dict[str, Any]:
        if persona not in PERSONAS:
            raise HTTPException(400, "unknown persona")
        p = PERSONAS[persona]
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": p["sub"],
            "email": p["sub"],
            "name": p["name"],
            "role": p["role"],
            "groups": groups if groups is not None else ROLE_GROUPS[p["role"]],
            "iat": now,
            "nbf": now - 5,
            "exp": now + ttl_s,
        }
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})
        return {"access_token": token, "id_token": token, "token_type": "Bearer", "expires_in": ttl_s}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/openid-configuration")
    async def discovery() -> dict[str, Any]:
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "subject_types_supported": ["public"],
        }

    @app.get("/jwks.json")
    async def jwks() -> dict[str, Any]:
        return {"keys": [jwk]}

    @app.get("/authorize", response_class=HTMLResponse)
    async def authorize_page(
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        state: str = "",
        response_type: str = "code",
        code_challenge_method: str = "S256",
    ) -> str:
        if response_type != "code" or code_challenge_method != "S256":
            raise HTTPException(400, "only response_type=code with S256 PKCE is supported")
        esc = html.escape
        buttons = "".join(
            f'<button name="persona" value="{name}" type="submit">{esc(p["name"])} — {esc(p["sub"])} ({esc(p["role"])})</button>'
            for name, p in PERSONAS.items()
        )
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Dev sign-in</title>"
            "<style>body{font-family:system-ui;max-width:32rem;margin:4rem auto;color:#111827;background:#FBFBF8}"
            "button{display:block;width:100%;margin:.5rem 0;padding:.75rem;font-size:1rem;cursor:pointer}</style>"
            "</head><body><h1>Northwind dev sign-in</h1><p>Synthetic personas for local development only.</p>"
            f"<form method='post' action='/authorize'><input type='hidden' name='client_id' value='{esc(client_id)}'>"
            f"<input type='hidden' name='redirect_uri' value='{esc(redirect_uri)}'>"
            f"<input type='hidden' name='code_challenge' value='{esc(code_challenge)}'>"
            f"<input type='hidden' name='state' value='{esc(state)}'>{buttons}</form></body></html>"
        )

    @app.post("/authorize")
    async def authorize_select(
        persona: str = Form(...),
        client_id: str = Form(...),
        redirect_uri: str = Form(...),
        code_challenge: str = Form(...),
        state: str = Form(""),
    ) -> RedirectResponse:
        if persona not in PERSONAS:
            raise HTTPException(400, "unknown persona")
        if not redirect_uri.startswith(("http://localhost:", "http://127.0.0.1:")):
            raise HTTPException(400, "redirect_uri must be a localhost URL")
        code = secrets.token_urlsafe(24)
        codes[code] = PendingCode(persona, client_id, redirect_uri, code_challenge, time.time() + CODE_TTL_S)
        return RedirectResponse(
            f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", status_code=302
        )

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        code = str(form.get("code", ""))
        pending = codes.pop(code, None)
        if (
            form.get("grant_type") != "authorization_code"
            or pending is None
            or pending.expires < time.time()
            or form.get("redirect_uri") != pending.redirect_uri
            or form.get("client_id") != pending.client_id
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        verifier = str(form.get("code_verifier", ""))
        computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not secrets.compare_digest(computed, pending.challenge):
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400
            )
        return JSONResponse(mint(pending.persona))

    @app.post("/dev/token")
    async def dev_token(req: DevTokenRequest) -> dict[str, Any]:
        return mint(req.persona, req.audience, req.ttl_s, req.groups)

    return app


app = create_app()
