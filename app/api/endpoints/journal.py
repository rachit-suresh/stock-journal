from fastapi import APIRouter, Request, Query, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_database
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

@router.get("/journal")
async def get_journal(service: JournalService = Depends(get_journal_service)):
    """Overview endpoint returning trades, strategies, and emotions."""
    data = await service.get_journal_overview()
    return {
        "success": True,
        "data": data
    }

@router.post("/journal/reset")
async def reset_journal(service: JournalService = Depends(get_journal_service)):
    """Reset database to initial mock state."""
    await service.reset_to_mock()
    return {"success": True, "message": "Database reset to mock state."}

@router.post("/journal/import")
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

# Backward Compatibility Router Handlers (Query Param Mode)
@router.post("/journal")
async def post_journal_compat(
    request: Request,
    action: str = Query(None),
    type: str = Query(None),
    service: JournalService = Depends(get_journal_service)
):
    try:
        body = await request.json() if await request.body() else {}
    except Exception:
        body = {}

    if action == "reset":
        await service.reset_to_mock()
        return {"success": True, "message": "Database reset to mock state."}

    if action == "import":
        trades = body.get("trades", [])
        strategies = body.get("strategies", [])
        emotions = body.get("emotions", [])
        await service.trade_repo.reset_trades(trades)
        await service.strategy_repo.reset_strategies(strategies)
        await service.emotion_repo.reset_emotions(emotions)
        return {"success": True, "message": "Journal imported successfully."}

    if type == "strategy":
        name = body.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Strategy name required.")
        added = await service.add_strategy(name)
        return {"success": added, "message": "Strategy added." if added else "Strategy already exists."}

    if type == "emotion":
        name = body.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Mindset name required.")
        added = await service.add_emotion(name)
        return {"success": added, "message": "Mindset added." if added else "Mindset already exists."}

    new_trade = await service.add_trade(body)
    return {"success": True, "data": new_trade}

@router.put("/journal")
async def put_journal_compat(
    request: Request,
    id: str = Query(None),
    service: JournalService = Depends(get_journal_service)
):
    if not id:
        raise HTTPException(status_code=400, detail="Trade ID required.")
    
    try:
        body = await request.json() if await request.body() else {}
    except Exception:
        body = {}

    updated = await service.update_trade(id, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Trade not found.")
        
    return {"success": True, "data": updated}

@router.delete("/journal")
async def delete_journal_compat(
    id: str = Query(None),
    type: str = Query(None),
    name: str = Query(None),
    service: JournalService = Depends(get_journal_service)
):
    if type == "strategy" and name:
        deleted = await service.delete_strategy(name)
        return {"success": deleted, "message": "Strategy deleted." if deleted else "Strategy not found."}
        
    if type == "emotion" and name:
        deleted = await service.delete_emotion(name)
        return {"success": deleted, "message": "Mindset deleted." if deleted else "Mindset not found."}

    if not id:
        raise HTTPException(status_code=400, detail="Trade ID required.")
        
    deleted = await service.delete_trade(id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade not found.")
        
    return {"success": True, "message": "Trade deleted successfully."}
