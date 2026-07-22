from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.repositories.interfaces.trade_repository import ITradeRepository

class MongoTradeRepository(ITradeRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db["trades"]

    async def get_all_trades(self) -> List[dict]:
        trades = []
        cursor = self.collection.find({})
        async for doc in cursor:
            mongo_id = str(doc.pop("_id"))
            doc["id"] = doc.pop("custom_id", mongo_id)
            trades.append(doc)
        return trades

    async def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        query = {"$or": [{"_id": ObjectId(trade_id)}, {"custom_id": trade_id}]} if ObjectId.is_valid(trade_id) else {"custom_id": trade_id}
        doc = await self.collection.find_one(query)
        if doc:
            mongo_id = str(doc.pop("_id"))
            doc["id"] = doc.pop("custom_id", mongo_id)
            return doc
        return None

    async def create_trade(self, trade: dict) -> dict:
        trade_data = dict(trade)
        custom_id = trade_data.pop("id", None)
        if custom_id and not ObjectId.is_valid(custom_id):
            trade_data["custom_id"] = custom_id

        result = await self.collection.insert_one(trade_data)
        trade_data["id"] = custom_id or str(result.inserted_id)
        trade_data.pop("_id", None)
        return trade_data

    async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]:
        query = {"$or": [{"_id": ObjectId(trade_id)}, {"custom_id": trade_id}]} if ObjectId.is_valid(trade_id) else {"custom_id": trade_id}
        
        clean_update = {k: v for k, v in trade_update.items() if v is not None}
        if not clean_update:
            return await self.get_trade_by_id(trade_id)

        await self.collection.update_one(query, {"$set": clean_update})
        return await self.get_trade_by_id(trade_id)

    async def delete_trade(self, trade_id: str) -> bool:
        query = {"$or": [{"_id": ObjectId(trade_id)}, {"custom_id": trade_id}]} if ObjectId.is_valid(trade_id) else {"custom_id": trade_id}
        result = await self.collection.delete_one(query)
        return result.deleted_count > 0

    async def reset_trades(self, trades: List[dict]) -> None:
        await self.collection.delete_many({})
        if trades:
            docs = []
            for t in trades:
                doc = dict(t)
                custom_id = doc.pop("id", None)
                if custom_id and not ObjectId.is_valid(custom_id):
                    doc["custom_id"] = custom_id
                docs.append(doc)
            await self.collection.insert_many(docs)
