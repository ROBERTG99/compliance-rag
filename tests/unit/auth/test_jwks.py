"""JWKS cache: stale keys outlive a failed refresh, and unknown key ids cannot force a fetch per request."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from compliance_rag.auth import jwt as jwt_module
from compliance_rag.auth.jwt import AuthError, JWKSCache


def _jwks() -> dict[str, Any]:
    public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    key = RSAAlgorithm.to_jwk(public, as_dict=True)
    return {"keys": [{**key, "kid": "k1", "alg": "RS256", "use": "sig"}]}


class Issuer:
    def __init__(self) -> None:
        self.calls = 0
        self.delay_s = 0.0
        self.up = True
        self.body = _jwks()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        await asyncio.sleep(self.delay_s)
        if not self.up:
            raise httpx.ConnectError("issuer down")
        return httpx.Response(200, json=self.body)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(jwt_module.time, "monotonic", lambda: now[0])
    return now


async def test_cached_keys_are_served_when_a_refresh_fails(clock: list[float]) -> None:
    issuer = Issuer()
    cache = JWKSCache("http://oidc", client=httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler)))
    assert await cache.key("k1")
    issuer.up = False
    clock[0] += 301  # past the TTL: a refresh is due and fails
    assert await cache.key("k1")  # a brief issuer outage must not sign every user out


async def test_unknown_key_ids_are_refetched_at_most_once_per_interval(clock: list[float]) -> None:
    issuer = Issuer()
    cache = JWKSCache("http://oidc", client=httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler)))
    await cache.key("k1")
    for _ in range(50):  # forged tokens with random kids
        with pytest.raises(AuthError):
            await cache.key("forged")
    assert issuer.calls == 1  # within the interval nothing is refetched, whatever the token says
    clock[0] += 11
    with pytest.raises(AuthError):
        await cache.key("forged")
    assert issuer.calls == 2  # then one refetch (a rotated key is picked up within ~10 s)


async def test_no_keys_and_no_issuer_is_an_auth_error(clock: list[float]) -> None:
    issuer = Issuer()
    issuer.up = False
    cache = JWKSCache("http://oidc", client=httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler)))
    with pytest.raises(AuthError, match="identity provider unavailable"):
        await cache.key("k1")


async def test_concurrent_first_requests_share_one_fetch() -> None:
    # every API worker starts with an empty cache: requests arriving while the first fetch is in flight wait
    # for it instead of failing as "unknown signing key" (a 401 signs the user out of the web app)
    issuer = Issuer()
    issuer.delay_s = 0.05
    cache = JWKSCache("http://oidc", client=httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler)))
    keys = await asyncio.gather(*(cache.key("k1") for _ in range(5)))
    assert all(keys) and issuer.calls == 1


async def test_stale_keys_are_not_served_forever(clock: list[float]) -> None:
    issuer = Issuer()
    cache = JWKSCache("http://oidc", client=httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler)))
    await cache.key("k1")
    issuer.up = False
    clock[0] += 3601  # past the maximum staleness while the issuer stays down
    with pytest.raises(AuthError, match="identity provider unavailable"):
        await cache.key("k1")
