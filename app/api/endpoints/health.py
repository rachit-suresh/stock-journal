from fastapi import APIRouter

from app.core.config import settings
from app.core.database import database_status
from app.streaming.price_cache import price_cache
from app.streaming.status import snapshot as streamer_snapshot

# Public, together with GET /auth/config (SPEC-API-10, SPEC-AUTH-2).
router = APIRouter()


@router.get("/health")
async def health():
    """Liveness plus a one-glance view of the market data pipeline.

    `streamer` describes the daemon (`mode`, `connected`, last state change)
    and `prices_fresh` tells you whether any tick landed inside the freshness
    window, which is what actually matters to a user looking at the screen.
    `database` is `unavailable` when the Postgres pool is missing or failing.
    """
    return {
        "status": "ok",
        "env": settings.ENV,
        "auth": settings.auth_mode(),
        "database": await database_status(),
        "streamer": streamer_snapshot(),
        "prices_fresh": price_cache.has_fresh_data(),
    }
