from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import settings
from app.core.database import get_database
from app.core.limits import mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.watchlist import WatchlistResponse, WatchlistUpdate
from app.repositories.mongo.watchlist_repository import MongoWatchlistRepository
from app.streaming.subscriptions import subscriptions

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_watchlist_repo(
    db: AsyncIOMotorDatabase = Depends(get_database),
    user: UserContext = Depends(get_current_user),
) -> MongoWatchlistRepository:
    return MongoWatchlistRepository(db, user.user_id)

def _effective_keys(stored: list[str]) -> list[str]:
    """An account that never saved one sees the shared default basket."""
    return stored if stored else settings.get_tokens()

@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist(
    repo: MongoWatchlistRepository = Depends(get_watchlist_repo),
    user: UserContext = Depends(get_current_user),
):
    """Return the caller's watchlist and keep its feed slots alive (GAP-9)."""
    keys = _effective_keys(await repo.get_keys())
    subscriptions.set_user_keys(user.user_id, keys)
    return {"success": True, "data": keys}

@router.put("/watchlist", response_model=WatchlistResponse,
            dependencies=[Depends(mutation_rate_limit)])
async def replace_watchlist(
    payload: WatchlistUpdate,
    repo: MongoWatchlistRepository = Depends(get_watchlist_repo),
    user: UserContext = Depends(get_current_user),
):
    """Replace the caller's watchlist; the streamer re-syncs within one cycle."""
    await repo.set_keys(payload.keys)
    subscriptions.set_user_keys(user.user_id, payload.keys)
    return {"success": True, "data": payload.keys}
