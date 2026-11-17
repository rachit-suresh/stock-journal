"""Indexes required by the multi-tenant model (SPEC-AUTH-8, GAP-6b).

Called once from the app lifespan. `partialFilterExpression` keeps legacy
documents (written before `owner_id` existed) out of the unique constraint so
startup cannot fail on pre-existing data.
"""

import logging

logger = logging.getLogger("indexes")


async def ensure_indexes(db) -> None:
    try:
        await db["trades"].create_index(
            [("owner_id", 1)],
            name="owner_trades",
            partialFilterExpression={"owner_id": {"$type": "string"}},
        )
        await db["strategies"].create_index(
            [("owner_id", 1), ("name_lower", 1)],
            name="owner_strategy_unique",
            unique=True,
            partialFilterExpression={"owner_id": {"$type": "string"}},
        )
        await db["emotions"].create_index(
            [("owner_id", 1), ("name_lower", 1)],
            name="owner_emotion_unique",
            unique=True,
            partialFilterExpression={"owner_id": {"$type": "string"}},
        )
        await db["watchlists"].create_index(
            [("owner_id", 1)],
            name="owner_watchlist_unique",
            unique=True,
            partialFilterExpression={"owner_id": {"$type": "string"}},
        )
        logger.info("Multi-tenant indexes are in place.")
    except Exception as e:
        # Never block startup on an index: the API stays correct, only the
        # concurrency guarantee weakens.
        logger.error(f"Could not create indexes: {e}")
