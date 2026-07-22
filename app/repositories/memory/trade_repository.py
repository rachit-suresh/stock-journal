from typing import List, Optional
from app.repositories.interfaces.trade_repository import ITradeRepository

class MemoryTradeRepository(ITradeRepository):
    def __init__(self, initial_trades: Optional[List[dict]] = None):
        self.trades = [dict(t) for t in (initial_trades or [])]

    async def get_all_trades(self) -> List[dict]:
        return [dict(t) for t in self.trades]

    async def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        for t in self.trades:
            if t.get("id") == trade_id or t.get("custom_id") == trade_id:
                return dict(t)
        return None

    async def create_trade(self, trade: dict) -> dict:
        trade_data = dict(trade)
        if "id" not in trade_data:
            trade_data["id"] = f"trade_mem_{len(self.trades) + 1}"
        self.trades.append(trade_data)
        return dict(trade_data)

    async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]:
        for idx, t in enumerate(self.trades):
            if t.get("id") == trade_id or t.get("custom_id") == trade_id:
                updated = {**t, **{k: v for k, v in trade_update.items() if v is not None}}
                self.trades[idx] = updated
                return dict(updated)
        return None

    async def delete_trade(self, trade_id: str) -> bool:
        for idx, t in enumerate(self.trades):
            if t.get("id") == trade_id or t.get("custom_id") == trade_id:
                self.trades.pop(idx)
                return True
        return False

    async def reset_trades(self, trades: List[dict]) -> None:
        self.trades = [dict(t) for t in trades]
