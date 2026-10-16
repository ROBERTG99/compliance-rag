"""Bearer JWT validation against the issuer's JWKS (RS256, audience, issuer, expiry)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from compliance_rag.auth.personas import ROLE_GROUPS
from compliance_rag.retrieval.types import Principal

ALGORITHMS = ["RS256"]


class AuthError(Exception):
    """Authentication failed (→ 401 problem+json)."""


class JWKSCache:
    def __init__(
        self, issuer_url: str, client: httpx.AsyncClient | None = None, ttl_s: float = 300.0
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=3.0)
        self.ttl_s = ttl_s
        self._keys: dict[str, PyJWK] = {}
        self._fetched = 0.0

    async def _refresh(self) -> None:
        resp = await self.client.get(f"{self.issuer_url}/jwks.json")
        resp.raise_for_status()
        self._keys = {k["kid"]: PyJWK(k) for k in resp.json()["keys"] if k.get("kid")}
        self._fetched = time.monotonic()

    async def key(self, kid: str) -> PyJWK:
        if kid not in self._keys or time.monotonic() - self._fetched > self.ttl_s:
            try:
                await self._refresh()
            except httpx.HTTPError as exc:
                raise AuthError("identity provider unavailable") from exc
        if kid not in self._keys:
            raise AuthError("unknown signing key")
        return self._keys[kid]


class TokenValidator:
    def __init__(self, issuer: str, audience: str, jwks: JWKSCache, leeway_s: int = 30) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks = jwks
        self.leeway_s = leeway_s

    async def claims(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("malformed token") from exc
        if header.get("alg") not in ALGORITHMS or not header.get("kid"):
            raise AuthError("unsupported token algorithm")
        key = await self.jwks.key(str(header["kid"]))
        try:
            return dict(
                jwt.decode(
                    token,
                    key.key,
                    algorithms=ALGORITHMS,
                    audience=self.audience,
                    issuer=self.issuer,
                    leeway=self.leeway_s,
                    options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                )
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError("invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthError("invalid issuer") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid token") from exc

    async def principal(self, token: str) -> Principal:
        claims = await self.claims(token)
        role = claims.get("role")
        if role not in ROLE_GROUPS:
            raise AuthError("unknown role")
        allowed = set(ROLE_GROUPS[role])
        groups = sorted(set(claims.get("groups") or []) & allowed) or sorted(allowed)
        return {"sub": str(claims["sub"]), "role": role, "groups": groups}
