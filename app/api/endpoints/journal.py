from fastapi import APIRouter, Request, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_database
from app.models.responses import JournalResponse, MessageResponse
from app.repositories.mongo.trade_repository import MongoTradeRepository
from app.repositories.mongo.strategy_repository import MongoStrategyRepository
from app.repositories.mongo.emotion_repository import MongoEmotionRepository
from app.services.journal_service import JournalService

router = APIRouter()

def get_journal_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> JournalService:
    trade_repo = MongoTradeRepository(db)
    strategy_repo = MongoStrategyRepository(db)
    emotion_repo = MongoEmotionRepository(db)
    return JournalService(trade_repo, strategy_repo, emotion_repo)

@router.get("/journal", response_model=JournalResponse)
async def get_journal(service: JournalService = Depends(get_journal_service)):
    """Overview endpoint returning trades, strategies, and emotions."""
    data = await service.get_journal_overview()
    return {
        "success": True,
        "data": data
    }

@router.post("/journal/reset", response_model=MessageResponse)
async def reset_journal(service: JournalService = Depends(get_journal_service)):
    """Reset database to initial mock state."""
    await service.reset_to_mock()
    return {"success": True, "message": "Database reset to mock state."}

@router.post("/journal/import", response_model=MessageResponse)
async def import_journal(request: Request, service: JournalService = Depends(get_journal_service)):
    """Import trades, strategies, and emotions from JSON payload."""
    body = await request.json()
    trades = body.get("trades", [])
    strategies = body.get("strategies", [])
    emotions = body.get("emotions", [])

    await service.trade_repo.reset_trades(trades)
    await service.strategy_repo.reset_strategies(strategies)
    await service.emotion_repo.reset_emotions(emotions)
    return {"success": True, "message": "Journal imported successfully."}
