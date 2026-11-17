from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_database
from app.models.responses import DataResponse, MessageResponse
from app.models.strategy import StrategyCreate
from app.repositories.mongo.strategy_repository import MongoStrategyRepository

router = APIRouter()

def get_strategy_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoStrategyRepository:
    return MongoStrategyRepository(db)

@router.get("/strategies", response_model=DataResponse[list[str]])
async def get_strategies(repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Fetch all strategy names."""
    strategies = await repo.get_all_strategies()
    return {"success": True, "data": strategies}

@router.post("/strategies", response_model=MessageResponse)
async def add_strategy(payload: StrategyCreate, repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Add a new custom strategy setup."""
    added = await repo.add_strategy(payload.name)
    if not added:
        raise HTTPException(status_code=400, detail="Strategy already exists or name is invalid.")
    return {"success": True, "message": f"Strategy '{payload.name}' added successfully."}

@router.delete("/strategies/{name}", response_model=MessageResponse)
async def delete_strategy(name: str, repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Delete a strategy by name and reassign linked trades to 'Uncategorized'."""
    deleted = await repo.delete_strategy(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found.")
    return {"success": True, "message": f"Strategy '{name}' deleted successfully."}
