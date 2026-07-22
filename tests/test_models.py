import pytest
from pydantic import ValidationError
from app.models.trade import TradeCreate, TradeUpdate, TradeResponse
from app.models.strategy import StrategyCreate
from app.models.emotion import EmotionCreate

def test_trade_create_valid():
    trade = TradeCreate(
        symbol="SBIN",
        side="BUY",
        price=650.50,
        shares=100,
        pfMatrix=1.5,
        strategy="Breakout"
    )
    assert trade.symbol == "SBIN"
    assert trade.side == "BUY"
    assert trade.price == 650.50
    assert trade.shares == 100
    assert trade.strategy == "Breakout"
    assert trade.emotion == "Neutral"
    assert trade.mistakes == ["None"]

def test_trade_create_invalid_price():
    with pytest.raises(ValidationError):
        TradeCreate(
            symbol="SBIN",
            side="BUY",
            price=-10.0,  # Invalid: gt=0
            shares=10
        )

def test_trade_create_invalid_shares():
    with pytest.raises(ValidationError):
        TradeCreate(
            symbol="SBIN",
            side="BUY",
            price=100.0,
            shares=0  # Invalid: gt=0
        )

def test_trade_update_partial():
    update = TradeUpdate(price=660.00, notes="Updated notes")
    update_dict = update.model_dump(exclude_unset=True)
    assert update_dict == {"price": 660.00, "notes": "Updated notes"}
    assert "symbol" not in update_dict

def test_strategy_create_valid():
    strat = StrategyCreate(name="Pullback Support")
    assert strat.name == "Pullback Support"

def test_strategy_create_invalid_empty():
    with pytest.raises(ValidationError):
        StrategyCreate(name="")

def test_emotion_create_valid():
    emo = EmotionCreate(name="Disciplined")
    assert emo.name == "Disciplined"
