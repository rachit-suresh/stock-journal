import re
from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.repositories.interfaces.emotion_repository import IEmotionRepository

class MongoEmotionRepository(IEmotionRepository):
    """Owner-scoped mindset tags, unique per owner (SPEC-AUTH-8)."""

    def __init__(self, db: AsyncIOMotorDatabase, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.collection = db["emotions"]
        self.trades_collection = db["trades"]

    async def get_all_emotions(self) -> List[str]:
        cursor = self.collection.find({"owner_id": self.owner_id})
        emotions = []
        async for doc in cursor:
            emotions.append(doc["name"])
        return emotions

    async def add_emotion(self, name: str) -> bool:
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
            if "duplicate key" in str(e).lower():
                return False
            raise
        return True

    async def delete_emotion(self, name: str) -> bool:
        pattern = f"^{re.escape(name.strip())}$"
        doc = await self.collection.find_one({
            "owner_id": self.owner_id,
            "name": {"$regex": pattern, "$options": "i"},
        })
        if not doc:
            return False

        actual_name = doc["name"]
        await self.collection.delete_one({"_id": doc["_id"], "owner_id": self.owner_id})

        # Re-assign this owner's trades to the neutral emotion
        await self.trades_collection.update_many(
            {"owner_id": self.owner_id, "emotion": actual_name},
            {"$set": {"emotion": "Neutral"}},
        )
        return True

    async def reset_emotions(self, emotions: List[str]) -> None:
        await self.collection.delete_many({"owner_id": self.owner_id})
        docs = [
            {
                "owner_id": self.owner_id,
                "name": e.strip(),
                "name_lower": e.strip().lower(),
            }
            for e in emotions if e.strip()
        ]
        if docs:
            await self.collection.insert_many(docs)
