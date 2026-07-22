import time
from fastapi import APIRouter, Query
from app.streaming.price_cache import price_cache

router = APIRouter()

@router.get("/prices")
async def get_prices(tokens: str = Query(None)):
    if not tokens:
        return {"data": {}, "timestamp": int(time.time() * 1000)}

    token_list = [t.strip() for t in tokens.split(",") if t.strip()]
    data = price_cache.get_batch_prices(token_list)

    return {
        "data": data,
        "timestamp": int(time.time() * 1000)
    }
