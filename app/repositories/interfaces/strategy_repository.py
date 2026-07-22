from abc import ABC, abstractmethod
from typing import List

class IStrategyRepository(ABC):
    @abstractmethod
    async def get_all_strategies(self) -> List[str]:
        """Fetch all strategy names."""
        pass

    @abstractmethod
    async def add_strategy(self, name: str) -> bool:
        """Add a new strategy name."""
        pass

    @abstractmethod
    async def delete_strategy(self, name: str) -> bool:
        """Delete a strategy by name."""
        pass

    @abstractmethod
    async def reset_strategies(self, strategies: List[str]) -> None:
        """Bulk replace all strategy tags."""
        pass
