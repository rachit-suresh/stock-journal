from typing import List, Optional
from app.repositories.interfaces.watchlist_repository import IWatchlistRepository

class MemoryWatchlistRepository(IWatchlistRepository):
    def __init__(self, owner_id: str, initial_keys: Optional[List[str]] = None):
        if not owner_id:
            raise ValueError("owner_id is required for owner-scoped repositories")
        self.owner_id = owner_id
        self.keys = list(initial_keys or [])

    async def get_keys(self) -> List[str]:
        return list(self.keys)

    async def set_keys(self, keys: List[str]) -> None:
        self.keys = list(keys)
