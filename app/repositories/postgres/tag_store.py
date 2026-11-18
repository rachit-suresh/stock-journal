"""Shared SQL for the two tag tables (strategies, emotions).

Both behave identically apart from the table, the trade field they cascade
into and the fallback tag, so the repositories delegate here. Table and field
names come from the constants below only, never from input.
"""

from typing import List

import asyncpg

_TABLES = {"strategies", "emotions"}


class TagStore:
    def __init__(self, pool: asyncpg.Pool, owner_id: str, table: str, trade_field: str, fallback: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        if table not in _TABLES:
            raise ValueError(f"unknown tag table {table!r}")
        self.pool = pool
        self.owner_id = owner_id
        self.table = table
        self.trade_field = trade_field
        self.fallback = fallback

    async def all(self) -> List[str]:
        rows = await self.pool.fetch(
            f"SELECT name FROM {self.table} WHERE owner_id = $1 ORDER BY seq",
            self.owner_id,
        )
        return [r["name"] for r in rows]

    async def add(self, name: str) -> bool:
        clean_name = name.strip()
        if not clean_name:
            return False
        # The unique (owner_id, lower(name)) index decides; a duplicate, even
        # one racing this request, is a no-op instead of an error (SPEC-PER-7).
        inserted = await self.pool.fetchval(
            f"INSERT INTO {self.table} (owner_id, name) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING RETURNING seq",
            self.owner_id, clean_name,
        )
        return inserted is not None

    async def delete(self, name: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                actual_name = await conn.fetchval(
                    f"DELETE FROM {self.table} WHERE owner_id = $1 AND lower(name) = lower($2) "
                    "RETURNING name",
                    self.owner_id, name.strip(),
                )
                if actual_name is None:
                    return False

                # Re-assign this owner's trades that used the stored casing.
                await conn.execute(
                    "UPDATE trades SET data = data || jsonb_build_object($2::text, $3::text) "
                    "WHERE owner_id = $1 AND data->>$2::text = $4",
                    self.owner_id, self.trade_field, self.fallback, actual_name,
                )
        return True

    async def reset(self, names: List[str]) -> None:
        rows = [(self.owner_id, n.strip()) for n in names if n.strip()]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(f"DELETE FROM {self.table} WHERE owner_id = $1", self.owner_id)
                if rows:
                    await conn.executemany(
                        f"INSERT INTO {self.table} (owner_id, name) VALUES ($1, $2) "
                        "ON CONFLICT DO NOTHING",
                        rows,
                    )
