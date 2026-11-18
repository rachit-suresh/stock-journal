"""Postgres schema for the multi-tenant journal (SPEC-PER-10).

Run once from the app lifespan. Every statement is idempotent, so a restart
against an existing Supabase project is a no-op. Row Level Security is enabled
with no policies: Supabase exposes the `public` schema over its REST API with
the browser's anon key, and RLS without policies denies that path entirely.
The backend connects as the table owner, which bypasses RLS.
"""

import logging

logger = logging.getLogger("database")

# Serializes concurrent boots (two instances or a quick restart) on one lock id.
_SCHEMA_LOCK_ID = 7_310_442_001

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    owner_id text NOT NULL,
    id       text NOT NULL,
    seq      bigint GENERATED ALWAYS AS IDENTITY,
    data     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX IF NOT EXISTS trades_owner_seq ON trades (owner_id, seq);

CREATE TABLE IF NOT EXISTS strategies (
    owner_id text NOT NULL,
    name     text NOT NULL CHECK (btrim(name) <> ''),
    seq      bigint GENERATED ALWAYS AS IDENTITY
);
CREATE UNIQUE INDEX IF NOT EXISTS strategies_owner_name ON strategies (owner_id, lower(name));

CREATE TABLE IF NOT EXISTS emotions (
    owner_id text NOT NULL,
    name     text NOT NULL CHECK (btrim(name) <> ''),
    seq      bigint GENERATED ALWAYS AS IDENTITY
);
CREATE UNIQUE INDEX IF NOT EXISTS emotions_owner_name ON emotions (owner_id, lower(name));

CREATE TABLE IF NOT EXISTS watchlists (
    owner_id   text PRIMARY KEY,
    keys       text[] NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE trades     ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE emotions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;
"""


async def ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_ID)
            await conn.execute(SCHEMA_SQL)
    logger.info("Postgres schema is in place (RLS enabled).")
