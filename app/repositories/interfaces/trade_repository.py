from abc import ABC, abstractmethod
from typing import List, Optional
from app.models.trade import TradeCreate, TradeUpdate, TradeResponse

class ITradeRepository(ABC):
    @abstractmethod
    async def get_all_trades(self) -> List[dict]:
        """Fetch all trades from storage."""
        pass

    @abstractmethod
    async def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        """Fetch single trade by ID."""
        pass

    @abstractmethod
    async def create_trade(self, trade: dict) -> dict:
        """Persist a new trade entry."""
        pass

    @abstractmethod
    async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]:
        """Update an existing trade entry."""
        pass

    @abstractmethod
    async def delete_trade(self, trade_id: str) -> bool:
        """Delete a trade entry by ID."""
        pass

    @abstractmethod
    async def reset_trades(self, trades: List[dict]) -> None:
        """Bulk replace all trades (for reset/import)."""
        pass
