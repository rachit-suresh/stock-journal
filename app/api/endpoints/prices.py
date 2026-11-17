import time
from fastapi import APIRouter, Query
from app.models.responses import PricesResponse
from app.streaming.price_cache import price_cache

router = APIRouter()

@router.get("/prices", response_model=PricesResponse)
async def get_prices(tokens: str = Query(None)):
    now_ms = int(time.time() * 1000)
    if not tokens:
        return {"success": True, "data": {}, "meta": {}, "timestamp": now_ms}

    token_list = [t.strip() for t in tokens.split(",") if t.strip()]

    return {
        "success": True,
        "data": price_cache.get_batch_prices(token_list),
        "meta": price_cache.get_batch_meta(token_list),
        "timestamp": now_ms
    }
