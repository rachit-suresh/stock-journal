import pytest
from app.repositories.memory.trade_repository import MemoryTradeRepository
from app.repositories.memory.strategy_repository import MemoryStrategyRepository
from app.repositories.memory.emotion_repository import MemoryEmotionRepository

@pytest.mark.asyncio
async def test_trade_repository_crud():
    repo = MemoryTradeRepository()
    
    # Create
    trade = await repo.create_trade({
        "symbol": "SBIN",
        "side": "BUY",
        "price": 650.0,
        "shares": 50,
        "strategy": "Breakout"
    })
    assert trade["symbol"] == "SBIN"
    trade_id = trade["id"]

    # Read
    fetched = await repo.get_trade_by_id(trade_id)
    assert fetched is not None
    assert fetched["price"] == 650.0

    # Update
    updated = await repo.update_trade(trade_id, {"price": 655.0, "notes": "Target revised"})
    assert updated["price"] == 655.0
    assert updated["notes"] == "Target revised"

    # Delete
    deleted = await repo.delete_trade(trade_id)
    assert deleted is True
    assert await repo.get_trade_by_id(trade_id) is None

@pytest.mark.asyncio
async def test_strategy_repository_duplicate_and_cascading_delete():
    trade_repo = MemoryTradeRepository()
    await trade_repo.create_trade({
        "id": "t1",
        "symbol": "TCS",
        "side": "BUY",
        "price": 3500.0,
        "shares": 10,
        "strategy": "Gap Fill"
    })

    strat_repo = MemoryStrategyRepository(["Gap Fill", "Breakout"], trade_repo=trade_repo)
    
    # Duplicate check (case-insensitive)
    assert await strat_repo.add_strategy("gap fill") is False
    assert await strat_repo.add_strategy("Trend") is True

    # Cascading delete
    assert await strat_repo.delete_strategy("Gap Fill") is True
    assert "Gap Fill" not in await strat_repo.get_all_strategies()

    # Trade using Gap Fill should be reassigned to Uncategorized
    t1 = await trade_repo.get_trade_by_id("t1")
    assert t1["strategy"] == "Uncategorized"

@pytest.mark.asyncio
async def test_emotion_repository_duplicate_and_cascading_delete():
    trade_repo = MemoryTradeRepository()
    await trade_repo.create_trade({
        "id": "t2",
        "symbol": "INFY",
        "side": "BUY",
        "price": 1500.0,
        "shares": 20,
        "emotion": "Anxious"
    })

    emo_repo = MemoryEmotionRepository(["Anxious", "Disciplined"], trade_repo=trade_repo)
    
    # Duplicate check
    assert await emo_repo.add_emotion("ANXIOUS") is False
    assert await emo_repo.add_emotion("FOMO") is True

    # Cascading delete
    assert await emo_repo.delete_emotion("Anxious") is True
    assert "Anxious" not in await emo_repo.get_all_emotions()

    # Trade using Anxious should be reassigned to Neutral
    t2 = await trade_repo.get_trade_by_id("t2")
    assert t2["emotion"] == "Neutral"
