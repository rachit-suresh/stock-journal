import asyncpg
from fastapi import APIRouter, HTTPException, Depends
from app.core.config import settings
from app.core.database import get_pool
from app.core.limits import enforce_cap, mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.emotion import EmotionCreate
from app.models.responses import DataResponse, MessageResponse
from app.repositories.postgres.emotion_repository import PostgresEmotionRepository

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_emotion_repo(
    pool: asyncpg.Pool = Depends(get_pool),
    user: UserContext = Depends(get_current_user),
) -> PostgresEmotionRepository:
    return PostgresEmotionRepository(pool, user.user_id)

@router.get("/emotions", response_model=DataResponse[list[str]])
async def get_emotions(repo: PostgresEmotionRepository = Depends(get_emotion_repo)):
    """Fetch all of the caller's mindset profiles."""
    emotions = await repo.get_all_emotions()
    return {"success": True, "data": emotions}

@router.post("/emotions", response_model=MessageResponse,
             dependencies=[Depends(mutation_rate_limit)])
async def add_emotion(payload: EmotionCreate, repo: PostgresEmotionRepository = Depends(get_emotion_repo)):
    """Add a new mindset profile."""
    enforce_cap(
        len(await repo.get_all_emotions()),
        settings.MAX_EMOTIONS_PER_USER,
        "Mindset profile",
    )
    added = await repo.add_emotion(payload.name)
    if not added:
        raise HTTPException(status_code=400, detail="Mindset profile already exists or name is invalid.")
    return {"success": True, "message": f"Mindset profile '{payload.name}' added successfully."}

@router.delete("/emotions/{name}", response_model=MessageResponse,
               dependencies=[Depends(mutation_rate_limit)])
async def delete_emotion(name: str, repo: PostgresEmotionRepository = Depends(get_emotion_repo)):
    """Delete a mindset profile and reassign linked trades to 'Neutral'."""
    deleted = await repo.delete_emotion(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mindset profile '{name}' not found.")
    return {"success": True, "message": f"Mindset profile '{name}' deleted successfully."}
