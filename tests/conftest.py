import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.config import settings
from app.core.limits import reset_rate_limit_buckets
from app.core.security import UserContext, get_current_user
from app.repositories.memory.trade_repository import MemoryTradeRepository
from app.repositories.memory.strategy_repository import MemoryStrategyRepository
from app.repositories.memory.emotion_repository import MemoryEmotionRepository
from app.repositories.memory.watchlist_repository import MemoryWatchlistRepository
from app.services.journal_service import JournalService
from app.api.endpoints.journal import get_journal_service
from app.api.endpoints.trades import get_trade_repo
from app.api.endpoints.strategies import get_strategy_repo
from app.api.endpoints.emotions import get_emotion_repo
from app.api.endpoints.watchlist import get_watchlist_repo
from app.streaming.subscriptions import subscriptions


def install_owner(owner_id: str):
    """Point every repository factory at an isolated in-memory owner."""
    trade = MemoryTradeRepository(owner_id)
    strategy = MemoryStrategyRepository(owner_id, ["Breakout", "Pullback Support"], trade_repo=trade)
    emotion = MemoryEmotionRepository(owner_id, ["Disciplined", "Confident"], trade_repo=trade)
    watchlist = MemoryWatchlistRepository(owner_id)
    service = JournalService(trade, strategy, emotion)

    app.dependency_overrides[get_current_user] = lambda: UserContext(user_id=owner_id)
    app.dependency_overrides[get_journal_service] = lambda: service
    app.dependency_overrides[get_trade_repo] = lambda: trade
    app.dependency_overrides[get_strategy_repo] = lambda: strategy
    app.dependency_overrides[get_emotion_repo] = lambda: emotion
    app.dependency_overrides[get_watchlist_repo] = lambda: watchlist

    return {
        "trade": trade,
        "strategy": strategy,
        "emotion": emotion,
        "watchlist": watchlist,
        "service": service,
    }


@pytest.fixture
def api():
    """Signed-in client for owner "user-a" with fresh in-memory storage."""
    repos = install_owner("user-a")
    reset_rate_limit_buckets()
    subscriptions.drop_user("user-a")
    client = TestClient(app)
    client.repos = repos
    yield client
    app.dependency_overrides.clear()
    reset_rate_limit_buckets()


@pytest.fixture
def anon_client(monkeypatch):
    """Client with authentication enforced and no Supabase network calls."""
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon-test-key")
    yield TestClient(app)
    app.dependency_overrides.clear()
