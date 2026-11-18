from typing import List

import asyncpg

from app.repositories.interfaces.emotion_repository import IEmotionRepository
from app.repositories.postgres.tag_store import TagStore


class PostgresEmotionRepository(IEmotionRepository):
    """Owner-scoped emotion tags; deleting one cascades trades to `Neutral`."""

    def __init__(self, pool: asyncpg.Pool, owner_id: str):
        self.owner_id = owner_id
        self.store = TagStore(pool, owner_id, "emotions", "emotion", "Neutral")

    async def get_all_emotions(self) -> List[str]:
        return await self.store.all()

    async def add_emotion(self, name: str) -> bool:
        return await self.store.add(name)

    async def delete_emotion(self, name: str) -> bool:
        return await self.store.delete(name)

    async def reset_emotions(self, emotions: List[str]) -> None:
        await self.store.reset(emotions)
