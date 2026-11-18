import asyncpg
from fastapi import APIRouter, Request, Depends, HTTPException
from app.core.config import settings
from app.core.database import get_pool
from app.core.limits import mutation_rate_limit
from app.core.security import UserContext, get_current_user
from app.models.responses import JournalResponse, MessageResponse
from app.repositories.postgres.trade_repository import PostgresTradeRepository
from app.repositories.postgres.strategy_repository import PostgresStrategyRepository
from app.repositories.postgres.emotion_repository import PostgresEmotionRepository
from app.services.journal_service import JournalService

router = APIRouter(dependencies=[Depends(get_current_user)])

def get_journal_service(
    pool: asyncpg.Pool = Depends(get_pool),
    user: UserContext = Depends(get_current_user),
) -> JournalService:
    """All three repositories are pinned to the caller's owner_id."""
    trade_repo = PostgresTradeRepository(pool, user.user_id)
    strategy_repo = PostgresStrategyRepository(pool, user.user_id)
    emotion_repo = PostgresEmotionRepository(pool, user.user_id)
    return JournalService(trade_repo, strategy_repo, emotion_repo)

@router.get("/journal", response_model=JournalResponse)
async def get_journal(service: JournalService = Depends(get_journal_service)):
    """Overview endpoint returning trades, strategies, and emotions."""
    data = await service.get_journal_overview()
    return {
        "success": True,
        "data": data
    }

@router.post("/journal/reset", response_model=MessageResponse,
             dependencies=[Depends(mutation_rate_limit)])
async def reset_journal(service: JournalService = Depends(get_journal_service)):
    """Reset only the caller's data back to the initial demo state."""
    await service.reset_to_mock()
    return {"success": True, "message": "Journal reset to the starter data."}

@router.post("/journal/import", response_model=MessageResponse,
             dependencies=[Depends(mutation_rate_limit)])
async def import_journal(request: Request, service: JournalService = Depends(get_journal_service)):
    """Replace the caller's journal with an exported JSON payload."""
    body = await request.json()
    trades = body.get("trades", [])
    strategies = body.get("strategies", [])
    emotions = body.get("emotions", [])

    if not isinstance(trades, list) or not isinstance(strategies, list) or not isinstance(emotions, list):
        raise HTTPException(status_code=400, detail="trades, strategies and emotions must be arrays.")

    if settings.MAX_TRADES_PER_USER > 0 and len(trades) > settings.MAX_TRADES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Imports are limited to {settings.MAX_TRADES_PER_USER} trades.",
        )

    # Repositories stamp owner_id themselves, so an imported file can never
    # write into somebody else's journal (SPEC-AUTH-7).
    await service.trade_repo.reset_trades(trades)
    await service.strategy_repo.reset_strategies(strategies)
    await service.emotion_repo.reset_emotions(emotions)
    return {"success": True, "message": "Journal imported successfully."}
