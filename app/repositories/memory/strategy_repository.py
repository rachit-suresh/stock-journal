from typing import List, Optional
from app.repositories.interfaces.strategy_repository import IStrategyRepository
from app.repositories.interfaces.trade_repository import ITradeRepository

class MemoryStrategyRepository(IStrategyRepository):
    def __init__(self, initial_strategies: Optional[List[str]] = None, trade_repo: Optional[ITradeRepository] = None):
        self.strategies = list(initial_strategies or [])
        self.trade_repo = trade_repo

    async def get_all_strategies(self) -> List[str]:
        return list(self.strategies)

    async def add_strategy(self, name: str) -> bool:
        clean = name.strip()
        if not clean:
            return False
        if any(s.lower() == clean.lower() for s in self.strategies):
            return False
        self.strategies.append(clean)
        return True

    async def delete_strategy(self, name: str) -> bool:
        match_idx = -1
        for idx, s in enumerate(self.strategies):
            if s.lower() == name.lower():
                match_idx = idx
                break
        if match_idx == -1:
            return False
            
        actual_name = self.strategies.pop(match_idx)
        
        # Soft cascading update on trades
        if self.trade_repo:
            trades = await self.trade_repo.get_all_trades()
            for t in trades:
                if t.get("strategy") == actual_name:
                    await self.trade_repo.update_trade(t.get("id"), {"strategy": "Uncategorized"})
        return True

    async def reset_strategies(self, strategies: List[str]) -> None:
        self.strategies = [s.strip() for s in strategies if s.strip()]
