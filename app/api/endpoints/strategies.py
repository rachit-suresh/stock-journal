from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import settings
from app.core.database import get_database
from app.core.limits import enforce_cap, mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.responses import DataResponse, MessageResponse
from app.models.strategy import StrategyCreate
from app.repositories.mongo.strategy_repository import MongoStrategyRepository

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_strategy_repo(
    db: AsyncIOMotorDatabase = Depends(get_database),
    user: UserContext = Depends(get_current_user),
) -> MongoStrategyRepository:
    return MongoStrategyRepository(db, user.user_id)

@router.get("/strategies", response_model=DataResponse[list[str]])
async def get_strategies(repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Fetch all of the caller's strategy names."""
    strategies = await repo.get_all_strategies()
    return {"success": True, "data": strategies}

@router.post("/strategies", response_model=MessageResponse,
             dependencies=[Depends(mutation_rate_limit)])
async def add_strategy(payload: StrategyCreate, repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Add a new custom strategy setup."""
    enforce_cap(
        len(await repo.get_all_strategies()),
        settings.MAX_STRATEGIES_PER_USER,
        "Strategy",
    )
    added = await repo.add_strategy(payload.name)
    if not added:
        raise HTTPException(status_code=400, detail="Strategy already exists or name is invalid.")
    return {"success": True, "message": f"Strategy '{payload.name}' added successfully."}

@router.delete("/strategies/{name}", response_model=MessageResponse,
               dependencies=[Depends(mutation_rate_limit)])
async def delete_strategy(name: str, repo: MongoStrategyRepository = Depends(get_strategy_repo)):
    """Delete a strategy by name and reassign linked trades to 'Uncategorized'."""
    deleted = await repo.delete_strategy(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found.")
    return {"success": True, "message": f"Strategy '{name}' deleted successfully."}
