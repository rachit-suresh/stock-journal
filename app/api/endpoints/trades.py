from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_database
from app.models.trade import TradeCreate, TradeUpdate
from app.repositories.mongo.trade_repository import MongoTradeRepository

router = APIRouter()

def get_trade_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoTradeRepository:
    return MongoTradeRepository(db)

@router.get("/trades")
async def get_all_trades(repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Fetch all trade entries from MongoDB."""
    trades = await repo.get_all_trades()
    return {"success": True, "data": trades}

@router.get("/trades/{trade_id}")
async def get_trade_by_id(trade_id: str, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Fetch a single trade entry by ID."""
    trade = await repo.get_trade_by_id(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "data": trade}

@router.post("/trades")
async def create_trade(payload: TradeCreate, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Record a new trade entry."""
    trade_dict = payload.model_dump()
    created = await repo.create_trade(trade_dict)
    return {"success": True, "data": created}

@router.put("/trades/{trade_id}")
async def update_trade(trade_id: str, payload: TradeUpdate, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Update an existing trade entry."""
    update_dict = payload.model_dump(exclude_unset=True)
    updated = await repo.update_trade(trade_id, update_dict)
    if not updated:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "data": updated}

@router.delete("/trades/{trade_id}")
async def delete_trade(trade_id: str, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Delete a trade entry by ID."""
    deleted = await repo.delete_trade(trade_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "message": "Trade deleted successfully."}
