import pytest
from fastapi.testclient import TestClient
from main import app
from app.core.database import get_database
from app.repositories.memory.trade_repository import MemoryTradeRepository
from app.repositories.memory.strategy_repository import MemoryStrategyRepository
from app.repositories.memory.emotion_repository import MemoryEmotionRepository
from app.services.journal_service import JournalService
from app.api.endpoints.journal import get_journal_service
from app.api.endpoints.trades import get_trade_repo
from app.api.endpoints.strategies import get_strategy_repo
from app.api.endpoints.emotions import get_emotion_repo

# Setup In-Memory Repository Context for API Integration Tests
memory_trade_repo = MemoryTradeRepository()
memory_strat_repo = MemoryStrategyRepository(["Breakout", "Pullback Support"], trade_repo=memory_trade_repo)
memory_emo_repo = MemoryEmotionRepository(["Disciplined", "Confident"], trade_repo=memory_trade_repo)
test_journal_service = JournalService(memory_trade_repo, memory_strat_repo, memory_emo_repo)

# Override FastAPI Dependencies for Isolation
app.dependency_overrides[get_journal_service] = lambda: test_journal_service
app.dependency_overrides[get_trade_repo] = lambda: memory_trade_repo
app.dependency_overrides[get_strategy_repo] = lambda: memory_strat_repo
app.dependency_overrides[get_emotion_repo] = lambda: memory_emo_repo

client = TestClient(app)

def test_get_prices_endpoint():
    res = client.get("/api/prices?tokens=3045,2885")
    assert res.status_code == 200
    json_data = res.json()
    assert json_data["success"] if "success" in json_data else True
    assert "data" in json_data
    assert "3045" in json_data["data"]
    assert "2885" in json_data["data"]

def test_strategies_api():
    # GET
    res = client.get("/api/strategies")
    assert res.status_code == 200
    assert "Breakout" in res.json()["data"]

    # POST (Add)
    res_add = client.post("/api/strategies", json={"name": "Gap Fill"})
    assert res_add.status_code == 200
    assert res_add.json()["success"] is True

    # Duplicate Add -> 400
    res_dup = client.post("/api/strategies", json={"name": "Gap Fill"})
    assert res_dup.status_code == 400

    # DELETE
    res_del = client.delete("/api/strategies/Gap Fill")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

def test_emotions_api():
    # GET
    res = client.get("/api/emotions")
    assert res.status_code == 200
    assert "Disciplined" in res.json()["data"]

    # POST (Add)
    res_add = client.post("/api/emotions", json={"name": "FOMO"})
    assert res_add.status_code == 200

    # DELETE
    res_del = client.delete("/api/emotions/FOMO")
    assert res_del.status_code == 200

def test_trades_api_crud():
    # POST (Create)
    trade_payload = {
        "symbol": "RELIANCE",
        "side": "BUY",
        "price": 2800.0,
        "shares": 15,
        "strategy": "Breakout",
        "emotion": "Confident",
        "notes": "Testing trade creation"
    }
    res_create = client.post("/api/trades", json=trade_payload)
    assert res_create.status_code == 200
    created = res_create.json()["data"]
    trade_id = created["id"]
    assert created["symbol"] == "RELIANCE"

    # GET All
    res_get_all = client.get("/api/trades")
    assert res_get_all.status_code == 200
    trades_list = res_get_all.json()["data"]
    assert any(t["id"] == trade_id for t in trades_list)

    # GET Single
    res_single = client.get(f"/api/trades/{trade_id}")
    assert res_single.status_code == 200
    assert res_single.json()["data"]["price"] == 2800.0

    # PUT (Update)
    res_update = client.put(f"/api/trades/{trade_id}", json={"price": 2850.0})
    assert res_update.status_code == 200
    assert res_update.json()["data"]["price"] == 2850.0

    # DELETE
    res_delete = client.delete(f"/api/trades/{trade_id}")
    assert res_delete.status_code == 200
    assert client.get(f"/api/trades/{trade_id}").status_code == 404

def test_journal_overview_and_reset():
    # Overview
    res = client.get("/api/journal")
    assert res.status_code == 200
    assert "trades" in res.json()["data"]
    assert "strategies" in res.json()["data"]
    assert "emotions" in res.json()["data"]

    # Reset
    res_reset = client.post("/api/journal/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["success"] is True
