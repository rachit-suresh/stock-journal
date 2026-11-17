from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import settings
from app.core.database import get_database
from app.core.limits import enforce_cap, mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.responses import DataResponse, MessageResponse
from app.models.trade import TradeCreate, TradeResponse, TradeUpdate
from app.repositories.mongo.trade_repository import MongoTradeRepository

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_trade_repo(
    db: AsyncIOMotorDatabase = Depends(get_database),
    user: UserContext = Depends(get_current_user),
) -> MongoTradeRepository:
    """Owner-scoped repository; tests override this factory (SPEC-API-9)."""
    return MongoTradeRepository(db, user.user_id)

@router.get("/trades", response_model=DataResponse[list[TradeResponse]])
async def get_all_trades(repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Fetch the caller's trade entries."""
    trades = await repo.get_all_trades()
    return {"success": True, "data": trades}

@router.get("/trades/{trade_id}", response_model=DataResponse[TradeResponse])
async def get_trade_by_id(trade_id: str, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Fetch one of the caller's trades by ID (404 for anyone else's)."""
    trade = await repo.get_trade_by_id(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "data": trade}

@router.post("/trades", response_model=DataResponse[TradeResponse],
             dependencies=[Depends(mutation_rate_limit)])
async def create_trade(payload: TradeCreate, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Record a new trade entry for the caller."""
    enforce_cap(
        len(await repo.get_all_trades()),
        settings.MAX_TRADES_PER_USER,
        "Trade",
    )
    # owner_id is never read from the payload (SPEC-AUTH-7).
    trade_dict = payload.model_dump()
    created = await repo.create_trade(trade_dict)
    return {"success": True, "data": created}

@router.put("/trades/{trade_id}", response_model=DataResponse[TradeResponse],
            dependencies=[Depends(mutation_rate_limit)])
async def update_trade(trade_id: str, payload: TradeUpdate, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Update an existing trade entry."""
    update_dict = payload.model_dump(exclude_unset=True)
    updated = await repo.update_trade(trade_id, update_dict)
    if not updated:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "data": updated}

@router.delete("/trades/{trade_id}", response_model=MessageResponse,
               dependencies=[Depends(mutation_rate_limit)])
async def delete_trade(trade_id: str, repo: MongoTradeRepository = Depends(get_trade_repo)):
    """Delete a trade entry by ID."""
    deleted = await repo.delete_trade(trade_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade entry not found.")
    return {"success": True, "message": "Trade deleted successfully."}
