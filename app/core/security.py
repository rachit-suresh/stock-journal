"""Clerk session verification for the FastAPI monolith.

The browser signs in with Clerk and sends its short-lived JWT as a bearer
token. This module verifies that token statically against Clerk's published
JWKS: no server-side session, no shared secret, no Clerk SDK on the server
(SPEC-AUTH-2/3). The verified `sub` claim is the tenancy key everywhere else.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger("security")

# Clerk signs RS256 today; ES256/HS256 are accepted so a project-level
# algorithm change does not take the API down.
ALLOWED_ALGORITHMS = ["RS256", "ES256", "HS256"]

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

                issuer = settings.CLERK_ISSUER.rstrip("/")
                _jwks_client = PyJWKClient(
                    f"{issuer}/.well-known/jwks.json",
                    cache_keys=True,
                    lifespan=3600,
                )
    return _jwks_client


def verify_session_token(token: str) -> dict:
    """Return the decoded claims of a Clerk session token or raise 401."""
    if not settings.CLERK_ISSUER:
        logger.error("CLERK_ISSUER is not set; every bearer token is rejected.")
        raise _unauthorized("Authentication is not configured on the server.")

    try:
        import jwt

        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            issuer=settings.CLERK_ISSUER,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:
        logger.info("Rejected bearer token: %s", exc)
        raise _unauthorized("Invalid or expired session token.") from exc


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserContext:
    """FastAPI dependency resolving the caller, or failing closed with 401.

    `AUTH_DISABLED` exists so local development does not need a Clerk project.
    It is refused outright when ENV=production (SPEC-AUTH-5).
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
