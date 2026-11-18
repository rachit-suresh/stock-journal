import uuid
from typing import List, Optional

import asyncpg

from app.repositories.interfaces.trade_repository import ITradeRepository

# Identity is owned by the row, never by the jsonb document.
_IDENTITY_KEYS = ("id", "owner_id", "custom_id", "_id")


def _payload(trade: dict) -> dict:
    return {k: v for k, v in dict(trade).items() if k not in _IDENTITY_KEYS}


def _to_trade(row) -> dict:
    trade = dict(row["data"])
    trade["id"] = row["id"]
    return trade


def _new_id() -> str:
    return uuid.uuid4().hex


class PostgresTradeRepository(ITradeRepository):
    """Owner-scoped trade storage (SPEC-PER-2..6).

    Every statement is filtered by `owner_id` (SPEC-AUTH-6), which comes from
    the verified session and never from a payload (SPEC-AUTH-7). A row owned
    by someone else is indistinguishable from a missing one, so callers keep
    returning 404 instead of 403. Fields live in one jsonb document so that
    imports keep their exact shape while GAP-2 is open.
    """

    def __init__(self, pool: asyncpg.Pool, owner_id: str):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.pool = pool

    async def get_all_trades(self) -> List[dict]:
        rows = await self.pool.fetch(
            "SELECT id, data FROM trades WHERE owner_id = $1 ORDER BY seq",
            self.owner_id,
        )
        return [_to_trade(r) for r in rows]

    async def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT id, data FROM trades WHERE owner_id = $1 AND id = $2",
            self.owner_id, trade_id,
        )
        return _to_trade(row) if row else None

    async def create_trade(self, trade: dict) -> dict:
        data = _payload(trade)
        trade_id = str(trade.get("id") or "") or _new_id()

        inserted = await self.pool.fetchval(
            "INSERT INTO trades (owner_id, id, data) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING RETURNING id",
            self.owner_id, trade_id, data,
        )
        if inserted is None:
            # A supplied id that already exists must not overwrite that trade.
            inserted = await self.pool.fetchval(
                "INSERT INTO trades (owner_id, id, data) VALUES ($1, $2, $3) RETURNING id",
                self.owner_id, _new_id(), data,
            )
        return {**data, "id": inserted}

    async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]:
        # Keys absent from the payload never reach here (exclude_unset upstream);
        # an explicit None is an intentional clear, so `||` writes a JSON null.
        patch = _payload(trade_update)
        if not patch:
            return await self.get_trade_by_id(trade_id)

        row = await self.pool.fetchrow(
            "UPDATE trades SET data = data || $3::jsonb "
            "WHERE owner_id = $1 AND id = $2 RETURNING id, data",
            self.owner_id, trade_id, patch,
        )
        return _to_trade(row) if row else None

    async def delete_trade(self, trade_id: str) -> bool:
        deleted = await self.pool.fetchval(
            "DELETE FROM trades WHERE owner_id = $1 AND id = $2 RETURNING id",
            self.owner_id, trade_id,
        )
        return deleted is not None

    async def reset_trades(self, trades: List[dict]) -> None:
        rows = []
        seen = set()
        for t in trades:
            trade_id = str(t.get("id") or "")
            if not trade_id or trade_id in seen:
                trade_id = _new_id()
            seen.add(trade_id)
            rows.append((self.owner_id, trade_id, _payload(t)))

        # One transaction: readers see the old journal or the new one, never
        # an empty one (SPEC-PER-6).
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM trades WHERE owner_id = $1", self.owner_id)
                if rows:
                    await conn.executemany(
                        "INSERT INTO trades (owner_id, id, data) VALUES ($1, $2, $3)",
                        rows,
                    )
