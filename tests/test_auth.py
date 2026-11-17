import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import encode as jwt_encode

from app.core import security
from app.core.config import settings
from app.core.security import get_current_user, verify_session_token
from app.streaming.subscriptions import subscriptions
from tests.conftest import install_owner

ISSUER = "https://example.clerk.accounts.dev"
KIND = {"symbol": "SBIN", "side": "BUY", "price": 650.0, "shares": 5}


# --- Authentication -------------------------------------------------------

def test_health_is_public(anon_client):
    res = anon_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "streamer" in body
    assert "prices_fresh" in body


def test_api_requires_bearer_token(anon_client):
    assert anon_client.get("/api/trades").status_code == 401
    assert anon_client.get("/api/prices?tokens=ABC").status_code == 401
    assert anon_client.post("/api/journal/reset").status_code == 401


def test_garbage_token_is_rejected(anon_client):
    res = anon_client.get("/api/trades", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401


def _fake_jwks(private_key):
    public_key = private_key.public_key()
    return SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)
    )


def _token(private_key, **overrides):
    claims = {
        "sub": "user-123",
        "iss": ISSUER,
        "exp": int(time.time()) + 120,
        "email": "trader@example.com",
    }
    claims.update(overrides)
    return jwt_encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_valid_token_yields_claims(monkeypatch, rsa_key):
    monkeypatch.setattr(settings, "CLERK_ISSUER", ISSUER)
    monkeypatch.setattr(security, "_jwks_client", _fake_jwks(rsa_key))

    claims = verify_session_token(_token(rsa_key))

    assert claims["sub"] == "user-123"
    assert claims["email"] == "trader@example.com"


def test_expired_token_is_rejected(monkeypatch, rsa_key):
    monkeypatch.setattr(settings, "CLERK_ISSUER", ISSUER)
    monkeypatch.setattr(security, "_jwks_client", _fake_jwks(rsa_key))

    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key, exp=int(time.time()) - 30))

    assert exc.value.status_code == 401


def test_token_from_another_issuer_is_rejected(monkeypatch, rsa_key):
    monkeypatch.setattr(settings, "CLERK_ISSUER", ISSUER)
    monkeypatch.setattr(security, "_jwks_client", _fake_jwks(rsa_key))

    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key, iss="https://evil.example.com"))

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_dev_bypass_is_local_only(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENV", "development")

    user = await get_current_user(credentials=None)
    assert user.user_id == settings.DEV_USER_ID
    assert user.authenticated is False


@pytest.mark.asyncio
async def test_dev_bypass_is_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=None)

    assert exc.value.status_code == 500


def test_startup_guard_blocks_production_bypass(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(RuntimeError):
        settings.validate_auth_config()


# --- Tenancy --------------------------------------------------------------

def test_cross_tenant_documents_are_invisible(api):
    created = api.post("/api/trades", json=KIND).json()["data"]

    install_owner("user-b")

    assert api.get("/api/trades").json()["data"] == []
    assert api.get(f"/api/trades/{created['id']}").status_code == 404
    assert api.delete(f"/api/trades/{created['id']}").status_code == 404


def test_owner_scoped_tags_allow_the_same_name_per_account(api):
    assert api.post("/api/strategies", json={"name": "Mine"}).status_code == 200

    install_owner("user-b")

    assert api.post("/api/strategies", json={"name": "Mine"}).status_code == 200
    assert "Mine" in api.get("/api/strategies").json()["data"]


async def test_reset_only_clears_the_callers_journal(api):
    created = api.post("/api/trades", json=KIND).json()["data"]
    user_a_trades = api.repos["trade"]

    install_owner("user-b")
    api.post("/api/journal/reset")

    other_ids = [t["id"] for t in api.get("/api/trades").json()["data"]]
    assert created["id"] not in other_ids
    # The reset re-seeds the caller's own starter journal, nothing else.
    assert "trade_1" in other_ids

    # user-a's journal was never touched by user-b's reset.
    assert any(t["id"] == created["id"] for t in await user_a_trades.get_all_trades())


def test_import_cannot_write_into_another_account(api):
    api.post("/api/journal/import", json={
        "trades": [{**KIND, "id": "imported-1", "owner_id": "someone-else"}],
        "strategies": ["Breakout"],
        "emotions": ["Neutral"],
    })

    install_owner("user-b")

    assert api.get("/api/trades").json()["data"] == []


# --- Abuse limits ---------------------------------------------------------

def test_trade_cap_is_enforced(api, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TRADES_PER_USER", 1)

    assert api.post("/api/trades", json=KIND).status_code == 200

    res = api.post("/api/trades", json=KIND)
    assert res.status_code == 400
    assert "limit reached" in res.json()["detail"].lower()


def test_mutation_rate_limit_returns_429(api, monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_RATE_LIMIT_PER_MINUTE", 2)

    assert api.post("/api/trades", json=KIND).status_code == 200
    assert api.post("/api/trades", json=KIND).status_code == 200

    res = api.post("/api/trades", json=KIND)
    assert res.status_code == 429
    assert res.headers["Retry-After"] == "60"


# --- Watchlist / subscriptions -------------------------------------------

def test_watchlist_defaults_and_roundtrip(api):
    default = api.get("/api/watchlist").json()["data"]
    assert default == settings.get_tokens()

    keys = ["NSE_EQ|INE002A01018", "NSE_EQ|INE467I01027"]
    res = api.put("/api/watchlist", json={"keys": keys})
    assert res.status_code == 200
    assert res.json()["data"] == keys
    assert api.get("/api/watchlist").json()["data"] == keys


def test_watchlist_rejects_invalid_keys(api):
    assert api.put("/api/watchlist", json={"keys": ["SBIN"]}).status_code == 422
    assert api.put("/api/watchlist", json={"keys": ["nse_eq|ine002a01018"]}).status_code == 200


def test_watchlist_keys_are_published_to_the_streamer(api):
    subscriptions.drop_user("user-a")
    api.put("/api/watchlist", json={"keys": ["NSE_EQ|INE002A01018"]})

    assert "NSE_EQ|INE002A01018" in subscriptions.snapshot()
