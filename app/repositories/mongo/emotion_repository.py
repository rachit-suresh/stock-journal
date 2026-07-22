from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.repositories.interfaces.emotion_repository import IEmotionRepository

class MongoEmotionRepository(IEmotionRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db["emotions"]
        self.trades_collection = db["trades"]

    async def get_all_emotions(self) -> List[str]:
        cursor = self.collection.find({})
        emotions = []
        async for doc in cursor:
            emotions.append(doc["name"])
        return emotions

    async def add_emotion(self, name: str) -> bool:
        clean_name = name.strip()
        if not clean_name:
            return False
            
        existing = await self.collection.find_one({"name": {"$regex": f"^{clean_name}$", "$options": "i"}})
        if existing:
            return False
            
        await self.collection.insert_one({"name": clean_name})
        return True

    async def delete_emotion(self, name: str) -> bool:
        doc = await self.collection.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
        if not doc:
            return False
            
        actual_name = doc["name"]
        await self.collection.delete_one({"_id": doc["_id"]})
        
        # Re-assign trades using this emotion profile to 'Neutral'
        await self.trades_collection.update_many(
            {"emotion": actual_name},
            {"$set": {"emotion": "Neutral"}}
        )
        return True

    async def reset_emotions(self, emotions: List[str]) -> None:
        await self.collection.delete_many({})
        if emotions:
            docs = [{"name": e.strip()} for e in emotions if e.strip()]
            await self.collection.insert_many(docs)
