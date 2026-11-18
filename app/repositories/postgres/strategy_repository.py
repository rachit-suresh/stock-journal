from typing import List

import asyncpg

from app.repositories.interfaces.strategy_repository import IStrategyRepository
from app.repositories.postgres.tag_store import TagStore


class PostgresStrategyRepository(IStrategyRepository):
    """Owner-scoped strategy tags; deleting one cascades trades to `Uncategorized`."""

    def __init__(self, pool: asyncpg.Pool, owner_id: str):
        self.owner_id = owner_id
        self.store = TagStore(pool, owner_id, "strategies", "strategy", "Uncategorized")

    async def get_all_strategies(self) -> List[str]:
        return await self.store.all()

    async def add_strategy(self, name: str) -> bool:
        return await self.store.add(name)

    async def delete_strategy(self, name: str) -> bool:
        return await self.store.delete(name)

    async def reset_strategies(self, strategies: List[str]) -> None:
        await self.store.reset(strategies)
