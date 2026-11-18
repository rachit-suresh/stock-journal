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

PROJECT_URL = "https://example.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
LEGACY_SECRET = "legacy-shared-secret-for-tests-only-0123456789"
KIND = {"symbol": "SBIN", "side": "BUY", "price": 650.0, "shares": 5}


# --- Authentication -------------------------------------------------------

def test_health_is_public(anon_client):
    res = anon_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["auth"] == "supabase"
    # The fixture never opens a pool, so the probe must report it, not crash.
    assert body["database"] == "unavailable"
    assert "streamer" in body
    # The two inputs that pick the mock streamer are reported explicitly.
    assert {"mock_requested", "upstox_token"} <= set(body["streamer"])
    assert "prices_fresh" in body


def test_auth_config_is_public_and_carries_the_project(anon_client):
    res = anon_client.get("/auth/config")
    assert res.status_code == 200
    assert res.json() == {
        "provider": "supabase",
        "url": PROJECT_URL,
        "anonKey": "anon-test-key",
    }


def test_auth_config_reports_dev_bypass(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    assert anon_client.get("/auth/config").json() == {"provider": "none"}


def test_api_requires_bearer_token(anon_client):
    assert anon_client.get("/api/trades").status_code == 401
    assert anon_client.get("/api/prices?tokens=ABC").status_code == 401
    assert anon_client.get("/api/journal").status_code == 401


def test_garbage_token_is_rejected(anon_client):
    res = anon_client.get("/api/trades", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401


def _fake_jwks(private_key):
    public_key = private_key.public_key()
    return SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)
    )


def _claims(**overrides):
    claims = {
        "sub": "user-123",
        "iss": ISSUER,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 120,
        "email": "trader@example.com",
    }
    claims.update(overrides)
    return claims


def _token(private_key, **overrides):
    return jwt_encode(_claims(**overrides), private_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def supabase_project(monkeypatch, rsa_key):
    monkeypatch.setattr(settings, "SUPABASE_URL", PROJECT_URL)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "")
    monkeypatch.setattr(security, "_jwks_client", _fake_jwks(rsa_key))


def test_valid_token_yields_claims(supabase_project, rsa_key):
    claims = verify_session_token(_token(rsa_key))

    assert claims["sub"] == "user-123"
    assert claims["email"] == "trader@example.com"


def test_expired_token_is_rejected(supabase_project, rsa_key):
    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key, exp=int(time.time()) - 30))

    assert exc.value.status_code == 401


def test_token_from_another_issuer_is_rejected(supabase_project, rsa_key):
    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key, iss="https://evil.supabase.co/auth/v1"))

    assert exc.value.status_code == 401


def test_anon_role_token_is_rejected(supabase_project, rsa_key):
    # The public anon key is itself a JWT; it must never pass as a user.
    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key, aud="anon", role="anon"))

    assert exc.value.status_code == 401


def test_token_without_audience_is_rejected(supabase_project, rsa_key):
    claims = _claims()
    del claims["aud"]
    token = jwt_encode(claims, rsa_key, algorithm="RS256", headers={"kid": "test-key"})

    with pytest.raises(HTTPException):
        verify_session_token(token)


def test_legacy_hs256_token_needs_the_secret(supabase_project, monkeypatch):
    token = jwt_encode(_claims(), LEGACY_SECRET, algorithm="HS256")

    with pytest.raises(HTTPException):
        verify_session_token(token)

    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", LEGACY_SECRET)
    assert verify_session_token(token)["sub"] == "user-123"


def test_hs256_token_signed_with_another_secret_is_rejected(supabase_project, monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", LEGACY_SECRET)
    token = jwt_encode(_claims(), "some-other-secret-that-is-long-enough-0123", algorithm="HS256")

    with pytest.raises(HTTPException):
        verify_session_token(token)


def test_missing_project_url_rejects_everything(supabase_project, monkeypatch, rsa_key):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")

    with pytest.raises(HTTPException) as exc:
        verify_session_token(_token(rsa_key))

    assert exc.value.status_code == 401


def test_valid_token_without_database_is_503_not_401(anon_client, supabase_project, rsa_key):
    # Auth runs first; a signed-in caller then learns the store is down.
    res = anon_client.get("/api/trades", headers={"Authorization": f"Bearer {_token(rsa_key)}"})
    assert res.status_code == 503


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


async def test_bulk_import_only_replaces_the_callers_journal(api):
    created = api.post("/api/trades", json=KIND).json()["data"]
    user_a_trades = api.repos["trade"]

    install_owner("user-b")
    api.post("/api/journal/import", json={"trades": [], "strategies": [], "emotions": []})

    assert api.get("/api/trades").json()["data"] == []

    # user-a's journal was never touched by user-b's import.
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

def test_watchlist_starts_empty_and_roundtrips(api):
    # No shared default basket: nothing is preloaded for a new account.
    assert api.get("/api/watchlist").json()["data"] == []

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
