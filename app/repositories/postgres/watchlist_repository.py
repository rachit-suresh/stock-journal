from typing import List

import asyncpg

from app.repositories.interfaces.watchlist_repository import IWatchlistRepository


class PostgresWatchlistRepository(IWatchlistRepository):
    """One row per owner in the `watchlists` table (SPEC-AUTH-14)."""

    def __init__(self, pool: asyncpg.Pool, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.pool = pool

    async def get_keys(self) -> List[str]:
        keys = await self.pool.fetchval(
            "SELECT keys FROM watchlists WHERE owner_id = $1", self.owner_id
        )
        return list(keys or [])

    async def set_keys(self, keys: List[str]) -> None:
        await self.pool.execute(
            "INSERT INTO watchlists (owner_id, keys, updated_at) VALUES ($1, $2, now()) "
            "ON CONFLICT (owner_id) DO UPDATE SET keys = EXCLUDED.keys, updated_at = now()",
            self.owner_id, list(keys),
        )
