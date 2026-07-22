from typing import List, Optional
from app.repositories.interfaces.emotion_repository import IEmotionRepository
from app.repositories.interfaces.trade_repository import ITradeRepository

class MemoryEmotionRepository(IEmotionRepository):
    def __init__(self, initial_emotions: Optional[List[str]] = None, trade_repo: Optional[ITradeRepository] = None):
        self.emotions = list(initial_emotions or [])
        self.trade_repo = trade_repo

    async def get_all_emotions(self) -> List[str]:
        return list(self.emotions)

    async def add_emotion(self, name: str) -> bool:
        clean = name.strip()
        if not clean:
            return False
        if any(e.lower() == clean.lower() for e in self.emotions):
            return False
        self.emotions.append(clean)
        return True

    async def delete_emotion(self, name: str) -> bool:
        match_idx = -1
        for idx, e in enumerate(self.emotions):
            if e.lower() == name.lower():
                match_idx = idx
                break
        if match_idx == -1:
            return False
            
        actual_name = self.emotions.pop(match_idx)
        
        # Soft cascading update on trades
        if self.trade_repo:
            trades = await self.trade_repo.get_all_trades()
            for t in trades:
                if t.get("emotion") == actual_name:
                    await self.trade_repo.update_trade(t.get("id"), {"emotion": "Neutral"})
        return True

    async def reset_emotions(self, emotions: List[str]) -> None:
        self.emotions = [e.strip() for e in emotions if e.strip()]
