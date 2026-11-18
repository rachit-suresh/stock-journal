"""asyncpg connection pool for Supabase Postgres (SPEC-S-2, SPEC-PER-11)."""

import json
import logging
from typing import Optional
from urllib.parse import parse_qs, urlparse

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.schema import ensure_schema

logger = logging.getLogger("database")

# Databases that are reached over loopback or a unix socket in development.
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


class DatabaseManager:
    pool: Optional[asyncpg.Pool] = None


db_manager = DatabaseManager()


async def _init_connection(conn: asyncpg.Connection) -> None:
    # Trades live in a jsonb column; let repositories pass plain dicts.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def ssl_mode_for(dsn: str) -> Optional[str]:
    """`require` for a hosted database, `None` to leave the decision alone.

    A DSN that already carries `sslmode` (or `ssl`) keeps its own answer, and
    loopback or socket targets stay plaintext so local dev and pgserver work.
    """
    parsed = urlparse(dsn)
    if {"sslmode", "ssl"} & {key.lower() for key in parse_qs(parsed.query)}:
        return None
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_HOSTS or host.endswith(".local"):
        return None
    return "require"


async def create_pool(dsn: str) -> asyncpg.Pool:
    # Hosted Postgres (Supabase included) refuses plaintext, but asyncpg reads a
    # DSN without `sslmode` as `disable`, so the handshake died before the
    # password was even checked. Ask for TLS unless the DSN says otherwise.
    ssl_mode = ssl_mode_for(dsn)
    # statement_cache_size=0: Supabase's pooler (Supavisor) cannot keep
    # server-side prepared statements across pooled connections.
    return await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=5,
        statement_cache_size=0,
        command_timeout=30,
        init=_init_connection,
        **{"ssl": ssl_mode} if ssl_mode else {},
    )


async def connect_to_database() -> None:
    """Open the pool and create the schema. Logs instead of raising, so the
    process still boots and /health can report the problem (SPEC-CFG-7)."""
    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL is not set; data routes will answer 503.")
        return

    try:
        db_manager.pool = await create_pool(settings.DATABASE_URL)
        logger.info("Connected to Postgres.")
    except Exception as e:
        # The DSN carries the password, so only the error is logged.
        logger.error(f"Failed to connect to Postgres: {e}")
        return

    try:
        await ensure_schema(db_manager.pool)
    except Exception as e:
        logger.error(f"Could not create the schema: {e}")


async def close_database_connection() -> None:
    if db_manager.pool is not None:
        logger.info("Closing Postgres pool...")
        await db_manager.pool.close()
        db_manager.pool = None


def get_pool() -> asyncpg.Pool:
    """FastAPI dependency: the shared pool, or 503 when there is none."""
    if db_manager.pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available.",
        )
    return db_manager.pool


async def database_status() -> str:
    """`ok` when a trivial query succeeds, otherwise `unavailable` (/health)."""
    if db_manager.pool is None:
        return "unavailable"
    try:
        await db_manager.pool.fetchval("SELECT 1", timeout=5)
        return "ok"
    except Exception as e:
        logger.warning(f"Health probe query failed: {e}")
        return "unavailable"
