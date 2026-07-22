from fastapi import APIRouter
from app.api.endpoints import prices, trades, strategies, emotions, journal

api_router = APIRouter()

api_router.include_router(prices.router, prefix="/api", tags=["Prices"])
api_router.include_router(trades.router, prefix="/api", tags=["Trades"])
api_router.include_router(strategies.router, prefix="/api", tags=["Strategies"])
api_router.include_router(emotions.router, prefix="/api", tags=["Emotions"])
api_router.include_router(journal.router, prefix="/api", tags=["Journal Overview & Maintenance"])
