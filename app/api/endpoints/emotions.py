from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_database
from app.models.emotion import EmotionCreate
from app.repositories.mongo.emotion_repository import MongoEmotionRepository

router = APIRouter()

def get_emotion_repo(db: AsyncIOMotorDatabase = Depends(get_database)) -> MongoEmotionRepository:
    return MongoEmotionRepository(db)

@router.get("/emotions")
async def get_emotions(repo: MongoEmotionRepository = Depends(get_emotion_repo)):
    """Fetch all mindset/emotion profile names."""
    emotions = await repo.get_all_emotions()
    return {"success": True, "data": emotions}

@router.post("/emotions")
async def add_emotion(payload: EmotionCreate, repo: MongoEmotionRepository = Depends(get_emotion_repo)):
    """Add a new custom mindset/emotion profile."""
    added = await repo.add_emotion(payload.name)
    if not added:
        raise HTTPException(status_code=400, detail="Mindset profile already exists or name is invalid.")
    return {"success": True, "message": f"Mindset '{payload.name}' added successfully."}

@router.delete("/emotions/{name}")
async def delete_emotion(name: str, repo: MongoEmotionRepository = Depends(get_emotion_repo)):
    """Delete a mindset profile by name and reassign linked trades to 'Neutral'."""
    deleted = await repo.delete_emotion(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mindset '{name}' not found.")
    return {"success": True, "message": f"Mindset '{name}' deleted successfully."}
