from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import settings
from app.core.database import get_database
from app.core.limits import enforce_cap, mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.emotion import EmotionCreate
from app.models.responses import DataResponse, MessageResponse
from app.repositories.mongo.emotion_repository import MongoEmotionRepository

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_emotion_repo(
    db: AsyncIOMotorDatabase = Depends(get_database),
    user: UserContext = Depends(get_current_user),
) -> MongoEmotionRepository:
    return MongoEmotionRepository(db, user.user_id)

@router.get("/emotions", response_model=DataResponse[list[str]])
async def get_emotions(repo: MongoEmotionRepository = Depends(get_emotion_repo)):
    """Fetch all of the caller's mindset profiles."""
    emotions = await repo.get_all_emotions()
    return {"success": True, "data": emotions}

@router.post("/emotions", response_model=MessageResponse,
             dependencies=[Depends(mutation_rate_limit)])
async def add_emotion(payload: EmotionCreate, repo: MongoEmotionRepository = Depends(get_emotion_repo)):
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
async def delete_emotion(name: str, repo: MongoEmotionRepository = Depends(get_emotion_repo)):
    """Delete a mindset profile and reassign linked trades to 'Neutral'."""
    deleted = await repo.delete_emotion(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mindset profile '{name}' not found.")
    return {"success": True, "message": f"Mindset profile '{name}' deleted successfully."}
