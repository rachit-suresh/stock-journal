import re
from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.repositories.interfaces.strategy_repository import IStrategyRepository

class MongoStrategyRepository(IStrategyRepository):
    """Owner-scoped strategy tags.

    Duplicates are prevented case-insensitively per owner, backed by the
    unique index on (owner_id, name_lower) so two concurrent requests cannot
    both pass the pre-check (SPEC-AUTH-8, GAP-6b).
    """

    def __init__(self, db: AsyncIOMotorDatabase, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.collection = db["strategies"]
        self.trades_collection = db["trades"]

    async def get_all_strategies(self) -> List[str]:
        cursor = self.collection.find({"owner_id": self.owner_id})
        strategies = []
        async for doc in cursor:
            strategies.append(doc["name"])
        return strategies

    async def add_strategy(self, name: str) -> bool:
        clean_name = name.strip()
        if not clean_name:
            return False

        pattern = f"^{re.escape(clean_name)}$"
        existing = await self.collection.find_one({
            "owner_id": self.owner_id,
            "name": {"$regex": pattern, "$options": "i"},
        })
        if existing:
            return False

        try:
            await self.collection.insert_one({
                "owner_id": self.owner_id,
                "name": clean_name,
                "name_lower": clean_name.lower(),
            })
        except Exception as e:
            # A duplicate key error means the index caught a concurrent insert.
            if "duplicate key" in str(e).lower():
                return False
            raise
        return True

    async def delete_strategy(self, name: str) -> bool:
        pattern = f"^{re.escape(name.strip())}$"
        doc = await self.collection.find_one({
            "owner_id": self.owner_id,
            "name": {"$regex": pattern, "$options": "i"},
        })
        if not doc:
            return False

        actual_name = doc["name"]
        await self.collection.delete_one({"_id": doc["_id"], "owner_id": self.owner_id})

        # Re-assign this owner's trades that used the strategy
        await self.trades_collection.update_many(
            {"owner_id": self.owner_id, "strategy": actual_name},
            {"$set": {"strategy": "Uncategorized"}},
        )
        return True

    async def reset_strategies(self, strategies: List[str]) -> None:
        await self.collection.delete_many({"owner_id": self.owner_id})
        docs = [
            {
                "owner_id": self.owner_id,
                "name": s.strip(),
                "name_lower": s.strip().lower(),
            }
            for s in strategies if s.strip()
        ]
        if docs:
            await self.collection.insert_many(docs)
