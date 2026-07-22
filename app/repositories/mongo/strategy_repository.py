import re
from typing import List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.repositories.interfaces.strategy_repository import IStrategyRepository

class MongoStrategyRepository(IStrategyRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db["strategies"]
        self.trades_collection = db["trades"]

    async def get_all_strategies(self) -> List[str]:
        cursor = self.collection.find({})
        strategies = []
        async for doc in cursor:
            strategies.append(doc["name"])
        return strategies

    async def add_strategy(self, name: str) -> bool:
        clean_name = name.strip()
        if not clean_name:
            return False
        
        pattern = f"^{re.escape(clean_name)}$"
        existing = await self.collection.find_one({"name": {"$regex": pattern, "$options": "i"}})
        if existing:
            return False
            
        await self.collection.insert_one({"name": clean_name})
        return True

    async def delete_strategy(self, name: str) -> bool:
        pattern = f"^{re.escape(name.strip())}$"
        doc = await self.collection.find_one({"name": {"$regex": pattern, "$options": "i"}})
        if not doc:
            return False
            
        actual_name = doc["name"]
        await self.collection.delete_one({"_id": doc["_id"]})
        
        # Re-assign trades using this strategy to 'Uncategorized'
        await self.trades_collection.update_many(
            {"strategy": actual_name},
            {"$set": {"strategy": "Uncategorized"}}
        )
        return True

    async def reset_strategies(self, strategies: List[str]) -> None:
        await self.collection.delete_many({})
        if strategies:
            docs = [{"name": s.strip()} for s in strategies if s.strip()]
            await self.collection.insert_many(docs)
