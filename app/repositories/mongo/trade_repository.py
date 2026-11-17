from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.repositories.interfaces.trade_repository import ITradeRepository

class MongoTradeRepository(ITradeRepository):
    """Owner-scoped trade storage.

    Every query is filtered by `owner_id` (SPEC-AUTH-6), which is assigned by
    the server from the verified session and never taken from a payload
    (SPEC-AUTH-7). A document belonging to someone else is indistinguishable
    from a missing one, so callers keep returning 404 instead of 403.
    """

    def __init__(self, db: AsyncIOMotorDatabase, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.collection = db["trades"]

    def _identity_query(self, trade_id: str) -> dict:
        if ObjectId.is_valid(trade_id):
            identity = {"$or": [{"_id": ObjectId(trade_id)}, {"custom_id": trade_id}]}
        else:
            identity = {"custom_id": trade_id}
        return {"$and": [{"owner_id": self.owner_id}, identity]}

    @staticmethod
    def _to_trade(doc: dict) -> dict:
        doc = dict(doc)
        mongo_id = str(doc.pop("_id"))
        doc.pop("owner_id", None)
        doc["id"] = doc.pop("custom_id", mongo_id)
        return doc

    async def get_all_trades(self) -> List[dict]:
        trades = []
        cursor = self.collection.find({"owner_id": self.owner_id})
        async for doc in cursor:
            trades.append(self._to_trade(doc))
        return trades

    async def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        doc = await self.collection.find_one(self._identity_query(trade_id))
        return self._to_trade(doc) if doc else None

    async def create_trade(self, trade: dict) -> dict:
        trade_data = dict(trade)
        trade_data.pop("owner_id", None)
        custom_id = trade_data.pop("id", None)
        if custom_id and not ObjectId.is_valid(custom_id):
            trade_data["custom_id"] = custom_id

        trade_data["owner_id"] = self.owner_id
        result = await self.collection.insert_one(trade_data)
        trade_data["id"] = custom_id or str(result.inserted_id)
        trade_data.pop("_id", None)
        trade_data.pop("owner_id", None)
        return trade_data

    async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]:
        query = self._identity_query(trade_id)

        if not trade_update:
            return await self.get_trade_by_id(trade_id)

        # Keys absent from the payload never reach here (exclude_unset upstream);
        # an explicit None is an intentional clear, so it is written as null.
        clean_update = {
            k: v for k, v in trade_update.items()
            if k not in ("id", "custom_id", "_id", "owner_id")
        }
        if not clean_update:
            return await self.get_trade_by_id(trade_id)

        await self.collection.update_one(query, {"$set": clean_update})
        return await self.get_trade_by_id(trade_id)

    async def delete_trade(self, trade_id: str) -> bool:
        result = await self.collection.delete_one(self._identity_query(trade_id))
        return result.deleted_count > 0

    async def reset_trades(self, trades: List[dict]) -> None:
        await self.collection.delete_many({"owner_id": self.owner_id})
        if not trades:
            return

        docs = []
        for t in trades:
            doc = dict(t)
            doc.pop("owner_id", None)
            custom_id = doc.pop("id", None)
            if custom_id and not ObjectId.is_valid(custom_id):
                doc["custom_id"] = custom_id
            doc["owner_id"] = self.owner_id
            docs.append(doc)
        await self.collection.insert_many(docs)
