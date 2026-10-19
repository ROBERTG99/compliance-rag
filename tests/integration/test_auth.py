"""Dev OIDC issuer and API token validation (FR-11, T-26)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest

from compliance_rag.auth.jwt import AuthError, JWKSCache, TokenValidator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "dev-oidc"))
from dev_oidc.app import create_app

ISSUER = "http://localhost:8612"


@pytest.fixture
def oidc() -> httpx.AsyncClient:
    app = create_app(public_url=ISSUER)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ISSUER)


def _validator(oidc: httpx.AsyncClient, audience: str = "compliance-rag") -> TokenValidator:
    return TokenValidator(issuer=ISSUER, audience=audience, jwks=JWKSCache(ISSUER, client=oidc))


async def _token(oidc: httpx.AsyncClient, persona: str, **extra: object) -> str:
    resp = await oidc.post("/dev/token", json={"persona": persona, **extra})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


async def test_wrong_audience_rejected(oidc: httpx.AsyncClient) -> None:
    token = await _token(oidc, "analyst", audience="another-app")
    with pytest.raises(AuthError, match="audience"):
        await _validator(oidc).principal(token)


async def test_personas_map_to_roles_and_groups(oidc: httpx.AsyncClient) -> None:
    validator = _validator(oidc)
    expected = {
        "analyst": ("analyst", ["all", "compliance"]),
        "legal": ("legal", ["all", "compliance", "legal"]),
        "support": ("support", ["all", "support"]),
        "admin": ("content_admin", ["all", "compliance"]),
    }
    for persona, (role, groups) in expected.items():
        principal = await validator.principal(await _token(oidc, persona))
        assert principal["role"] == role and sorted(principal["groups"]) == groups
        assert principal["sub"].endswith("@northwind.test")


async def test_expired_tampered_and_foreign_tokens_rejected(oidc: httpx.AsyncClient) -> None:
    validator = _validator(oidc)
    with pytest.raises(AuthError, match="expired"):
        await validator.principal(await _token(oidc, "analyst", ttl_s=-60))
    good = await _token(oidc, "support")
    header, _payload, sig = good.split(".")
    claims = jwt.decode(good, options={"verify_signature": False})
    claims["groups"] = ["legal", "all"]
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(AuthError):
        await validator.principal(f"{header}.{forged_payload}.{sig}")
    from cryptography.hazmat.primitives.asymmetric import rsa

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign = jwt.encode(
        {**claims, "exp": int(time.time()) + 60}, other_key, algorithm="RS256", headers={"kid": "x"}
    )
    with pytest.raises(AuthError):
        await validator.principal(foreign)
    with pytest.raises(AuthError):
        await validator.principal(jwt.encode({**claims}, "secret", algorithm="HS256"))


async def test_token_claims_cannot_escalate_groups(oidc: httpx.AsyncClient) -> None:
    principal = await _validator(oidc).principal(
        await _token(oidc, "support", groups=["legal", "support", "all"])
    )
    assert "legal" not in principal["groups"]  # groups are capped by the role


async def test_pkce_authorization_code_flow(oidc: httpx.AsyncClient) -> None:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    redirect = "http://localhost:8600/callback"
    page = await oidc.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "crag-web",
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
        },
    )
    assert page.status_code == 200 and "legal@northwind.test" in page.text
    resp = await oidc.post(
        "/authorize",
        data={
            "persona": "legal",
            "client_id": "crag-web",
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "state": "xyz",
        },
    )
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["state"] == ["xyz"]
    bad = await oidc.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "code_verifier": "wrong",
            "redirect_uri": redirect,
            "client_id": "crag-web",
        },
    )
    assert bad.status_code == 400
    resp = await oidc.post(
        "/authorize",
        data={
            "persona": "legal",
            "client_id": "crag-web",
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "state": "xyz",
        },
    )
    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]
    token = await oidc.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "client_id": "crag-web",
        },
    )
    assert token.status_code == 200
    principal = await _validator(oidc).principal(token.json()["access_token"])
    assert principal["role"] == "legal"
    reuse = await oidc.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "client_id": "crag-web",
        },
    )
    assert reuse.status_code == 400  # codes are single use


@pytest.mark.parametrize(
    "redirect",
    [
        "http://localhost:@evil.example/callback",  # "localhost:" as user info, evil.example as the host
        "http://localhost:8600@evil.example/callback",
        "http://evil.example/callback",
        "http://localhost:8601/callback",
        "http://localhost:8600/callback/../steal",
        "javascript:alert(1)",
    ],
)
async def test_authorize_redirects_only_to_registered_uris(oidc: httpx.AsyncClient, redirect: str) -> None:
    query = {
        "response_type": "code",
        "client_id": "crag-web",
        "redirect_uri": redirect,
        "code_challenge": "c",
    }
    assert (await oidc.get("/authorize", params=query)).status_code == 400
    form = {"persona": "legal", "client_id": "crag-web", "redirect_uri": redirect, "code_challenge": "c"}
    assert (await oidc.post("/authorize", data=form)).status_code == 400


async def test_authorize_redirects_to_the_registered_uri(oidc: httpx.AsyncClient) -> None:
    form = {"persona": "legal", "client_id": "crag-web", "redirect_uri": "http://127.0.0.1:8600/callback"}
    resp = await oidc.post("/authorize", data={**form, "code_challenge": "c", "state": "s"})
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("http://127.0.0.1:8600/callback?code=")


async def test_discovery_document(oidc: httpx.AsyncClient) -> None:
    doc = (await oidc.get("/.well-known/openid-configuration")).json()
    assert doc["issuer"] == ISSUER and doc["jwks_uri"].endswith("/jwks.json")
    assert "S256" in doc["code_challenge_methods_supported"]
