import logging
from typing import Any, Dict

from app.repositories.interfaces.emotion_repository import IEmotionRepository
from app.repositories.interfaces.strategy_repository import IStrategyRepository
from app.repositories.interfaces.trade_repository import ITradeRepository

logger = logging.getLogger("journal-service")

# A new account starts with an empty journal. There are no demo trades and no
# reset-to-demo route: the dashboard walkthrough teaches the user to record
# their own positions instead of inheriting somebody else's.
DEFAULT_STRATEGIES = ["Breakout", "Pullback Support", "Gap Fill", "Trend Continuation", "Mean Reversion"]
DEFAULT_EMOTIONS = ["Disciplined", "Confident", "Neutral", "Anxious", "FOMO", "Greedy"]


class JournalService:
    def __init__(
        self,
        trade_repo: ITradeRepository,
        strategy_repo: IStrategyRepository,
        emotion_repo: IEmotionRepository
    ):
        self.trade_repo = trade_repo
        self.strategy_repo = strategy_repo
        self.emotion_repo = emotion_repo

    async def seed_default_tags(self):
        """Seeds the strategy/emotion tag library of an empty account.

        Trades are deliberately never seeded: an empty journal is the honest
        state of a new account, and the UI shows a walkthrough for it.
        """
        strategies = await self.strategy_repo.get_all_strategies()
        emotions = await self.emotion_repo.get_all_emotions()

        if not strategies:
            logger.info("Seeding default strategies...")
            await self.strategy_repo.reset_strategies(DEFAULT_STRATEGIES)

        if not emotions:
            logger.info("Seeding default emotions...")
            await self.emotion_repo.reset_emotions(DEFAULT_EMOTIONS)

    async def get_journal_overview(self) -> Dict[str, Any]:
        await self.seed_default_tags()
        trades = await self.trade_repo.get_all_trades()
        strategies = await self.strategy_repo.get_all_strategies()
        emotions = await self.emotion_repo.get_all_emotions()

        return {
            "trades": trades,
            "strategies": strategies,
            "emotions": emotions
        }

    async def add_trade(self, trade_data: dict) -> dict:
        return await self.trade_repo.create_trade(trade_data)

    async def update_trade(self, trade_id: str, trade_update: dict) -> dict:
        return await self.trade_repo.update_trade(trade_id, trade_update)

    async def delete_trade(self, trade_id: str) -> bool:
        return await self.trade_repo.delete_trade(trade_id)

    async def add_strategy(self, name: str) -> bool:
        return await self.strategy_repo.add_strategy(name)

    async def delete_strategy(self, name: str) -> bool:
        return await self.strategy_repo.delete_strategy(name)

    async def add_emotion(self, name: str) -> bool:
        return await self.emotion_repo.add_emotion(name)

    async def delete_emotion(self, name: str) -> bool:
        return await self.emotion_repo.delete_emotion(name)
