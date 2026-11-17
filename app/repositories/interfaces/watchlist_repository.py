from abc import ABC, abstractmethod
from typing import List

class IWatchlistRepository(ABC):
    """Per-owner instrument list that drives live subscriptions (GAP-9)."""

    @abstractmethod
    async def get_keys(self) -> List[str]:
        """Return this owner's instrument keys, or an empty list when unset."""
        pass

    @abstractmethod
    async def set_keys(self, keys: List[str]) -> None:
        """Replace this owner's instrument keys."""
        pass
