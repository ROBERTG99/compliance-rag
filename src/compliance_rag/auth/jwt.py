"""Bearer JWT validation against the issuer's JWKS (RS256, audience, issuer, expiry)."""

from __future__ import annotations

import asyncio
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
        self,
        issuer_url: str,
        client: httpx.AsyncClient | None = None,
        ttl_s: float = 300.0,
        min_refetch_s: float = 10.0,
        max_stale_s: float = 3600.0,
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=3.0)
        self.ttl_s = ttl_s
        self.min_refetch_s = (
            min_refetch_s  # unknown key ids (rotation, or forged tokens) refetch at most this often
        )
        self.max_stale_s = max_stale_s  # cached keys outlive a failed refresh, but not indefinitely
        self._keys: dict[str, PyJWK] = {}
        self._fetched = float("-inf")
        self._attempted = float("-inf")  # when the last fetch finished, successful or not
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        try:
            resp = await self.client.get(f"{self.issuer_url}/jwks.json")
            resp.raise_for_status()
            self._keys = {k["kid"]: PyJWK(k) for k in resp.json()["keys"] if k.get("kid")}
            self._fetched = time.monotonic()
        finally:
            self._attempted = time.monotonic()

    def _due(self, kid: str) -> bool:
        now = time.monotonic()
        if not self._keys:
            return True
        expired = now - self._fetched > self.ttl_s
        return (expired or kid not in self._keys) and now - self._attempted >= self.min_refetch_s

    async def key(self, kid: str) -> PyJWK:
        if self._due(kid):
            async with self._lock:  # one fetch at a time; requests that waited see its result
                if self._due(kid):
                    try:
                        await self._refresh()
                    except httpx.HTTPError as exc:
                        if not self._keys or time.monotonic() - self._fetched > self.max_stale_s:
                            raise AuthError("identity provider unavailable") from exc
                        # keep serving the keys we have: a brief issuer outage must not sign everyone out
        if time.monotonic() - self._fetched > self.max_stale_s:
            raise AuthError("identity provider unavailable")
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
