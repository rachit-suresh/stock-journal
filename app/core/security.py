"""Supabase session verification for the FastAPI monolith.

The browser signs in with Supabase Auth and sends its short-lived access
token as a bearer token. This module verifies that token statically: against
the project's published JWKS for asymmetric signing keys, or against the
legacy shared secret when a project still signs HS256 (SPEC-AUTH-2/3). No
server-side session and no Supabase SDK on the server. The verified `sub`
claim is the tenancy key everywhere else.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger("security")

# Supabase asymmetric signing keys are ES256 (default) or RS256.
ASYMMETRIC_ALGORITHMS = ["RS256", "ES256"]
# Legacy projects sign with a shared secret; accepted only when it is set.
LEGACY_ALGORITHM = "HS256"
# Every signed-in user's access token carries this audience.
SUPABASE_AUDIENCE = "authenticated"

_bearer_scheme = HTTPBearer(auto_error=False)
_jwks_client = None
_jwks_lock = threading.Lock()


@dataclass(frozen=True)
class UserContext:
    """The caller identity handed to every repository factory."""

    user_id: str
    email: Optional[str] = None
    authenticated: bool = True


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _get_jwks_client():
    """Build the JWKS client once per process (SPEC-NF-6)."""
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                from jwt import PyJWKClient

                _jwks_client = PyJWKClient(
                    f"{settings.supabase_issuer()}/.well-known/jwks.json",
                    cache_keys=True,
                    lifespan=3600,
                )
    return _jwks_client


def _verification_key(token: str):
    """Pick the key and the single algorithm family the token may use.

    The algorithm list is derived from the configured key type, never from
    the token alone, so an HS256 token can never be checked against a public
    JWKS key (algorithm confusion).
    """
    import jwt

    algorithm = jwt.get_unverified_header(token).get("alg")
    if algorithm == LEGACY_ALGORITHM:
        if not settings.SUPABASE_JWT_SECRET:
            raise ValueError("HS256 token but SUPABASE_JWT_SECRET is not set")
        return settings.SUPABASE_JWT_SECRET, [LEGACY_ALGORITHM]
    if algorithm in ASYMMETRIC_ALGORITHMS:
        return _get_jwks_client().get_signing_key_from_jwt(token).key, ASYMMETRIC_ALGORITHMS
    raise ValueError(f"unsupported signing algorithm {algorithm!r}")


def verify_session_token(token: str) -> dict:
    """Return the decoded claims of a Supabase access token or raise 401."""
    if not settings.SUPABASE_URL:
        logger.error("SUPABASE_URL is not set; every bearer token is rejected.")
        raise _unauthorized("Authentication is not configured on the server.")

    try:
        import jwt

        key, algorithms = _verification_key(token)
        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            issuer=settings.supabase_issuer(),
            audience=SUPABASE_AUDIENCE,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except Exception as exc:
        logger.info("Rejected bearer token: %s", exc)
        raise _unauthorized("Invalid or expired session token.") from exc


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserContext:
    """FastAPI dependency resolving the caller, or failing closed with 401.

    `AUTH_DISABLED` exists so local development does not need a Supabase
    project. It is refused outright when ENV=production (SPEC-AUTH-5).
    """
    if settings.AUTH_DISABLED:
        if settings.is_production():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AUTH_DISABLED is not allowed when ENV=production.",
            )
        return UserContext(
            user_id=settings.DEV_USER_ID,
            email="dev@localhost",
            authenticated=False,
        )

    if credentials is None or not credentials.credentials:
        raise _unauthorized("Sign-in required.")

    claims = verify_session_token(credentials.credentials)
    return UserContext(user_id=claims["sub"], email=claims.get("email"))
