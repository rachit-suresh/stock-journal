from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.repositories.interfaces.watchlist_repository import IWatchlistRepository

class MongoWatchlistRepository(IWatchlistRepository):
    """One document per owner in the `watchlists` collection."""

    def __init__(self, db: AsyncIOMotorDatabase, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.collection = db["watchlists"]

    async def get_keys(self) -> List[str]:
        doc = await self.collection.find_one({"owner_id": self.owner_id})
        if not doc:
            return []
        return list(doc.get("keys") or [])

    async def set_keys(self, keys: List[str]) -> None:
        await self.collection.update_one(
            {"owner_id": self.owner_id},
            {"$set": {"owner_id": self.owner_id, "keys": list(keys)}},
            upsert=True,
        )
