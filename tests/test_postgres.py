"""Integration tests for the Postgres layer (SPEC-PER-10..14).

These run against a real PostgreSQL instance, because the behaviour under
test is SQL: jsonb merge semantics, the partial-clear rule, ON CONFLICT
de-duplication, cascade updates and the reset transaction. A throwaway
cluster is started with the `pgserver` package; without it (or with
TEST_DATABASE_URL pointing at an existing database) the module skips.
"""

import atexit
import os
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.database import create_pool
from app.core.schema import ensure_schema
from app.repositories.postgres.emotion_repository import PostgresEmotionRepository
from app.repositories.postgres.strategy_repository import PostgresStrategyRepository
from app.repositories.postgres.trade_repository import PostgresTradeRepository
from app.repositories.postgres.watchlist_repository import PostgresWatchlistRepository
from app.services.journal_service import (
    DEFAULT_EMOTIONS,
    DEFAULT_STRATEGIES,
    INITIAL_TRADES,
    JournalService,
)

TRADE = {
    "symbol": "SBIN",
    "side": "BUY",
    "price": 650.0,
    "stopLoss": 640.0,
    "shares": 5,
    "strategy": "Breakout",
    "emotion": "Disciplined",
    "mistakes": ["None"],
    "notes": "",
    "date": "2026-11-18T09:30:00Z",
}


@pytest.fixture(scope="session")
def database_uri():
    """TEST_DATABASE_URL when provided, else a private pgserver cluster."""
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit

    pgserver = pytest.importorskip(
        "pgserver", reason="install pgserver or set TEST_DATABASE_URL"
    )
    data_dir = Path(__file__).resolve().parent.parent / ".pgtest"
    server = pgserver.get_server(str(data_dir), cleanup_mode="stop")
    try:
        yield server.get_uri()
    finally:
        # Stop the cluster here rather than in pgserver's atexit hook, which
        # fires after pytest has closed the streams it logs to.
        server.cleanup()
        atexit.unregister(server._cleanup)


@pytest.fixture
async def pool(database_uri):
    pool = await create_pool(database_uri)
    await ensure_schema(pool)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def owner() -> str:
    """A fresh tenant per test, so cases never see each other's rows."""
    return f"user-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def trades(pool, owner):
    return PostgresTradeRepository(pool, owner)


@pytest.fixture
def strategies(pool, owner):
    return PostgresStrategyRepository(pool, owner)


@pytest.fixture
def emotions(pool, owner):
    return PostgresEmotionRepository(pool, owner)


# --- Schema ---------------------------------------------------------------

async def test_schema_enables_rls_without_policies(pool):
    tables = ["trades", "strategies", "emotions", "watchlists"]
    rows = await pool.fetch(
        "SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY($1)",
        tables,
    )
    assert {r["relname"] for r in rows} == set(tables)
    assert all(r["relrowsecurity"] for r in rows)

    # No policies means the anon key can read nothing, while the table owner
    # (the backend) is unaffected.
    policies = await pool.fetchval(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public'"
    )
    assert policies == 0


# --- Trades ---------------------------------------------------------------

async def test_trades_keep_insert_order_and_generate_ids(trades, owner):
    first = await trades.create_trade({**TRADE, "symbol": "SBIN"})
    second = await trades.create_trade({**TRADE, "symbol": "INFY"})

    assert first["id"] and first["id"] != second["id"]
    assert "owner_id" not in first and "_id" not in first

    all_trades = await trades.get_all_trades()
    assert [t["symbol"] for t in all_trades] == ["SBIN", "INFY"]
    assert all_trades[0]["stopLoss"] == 640.0
    assert await trades.get_trade_by_id(first["id"]) == first


async def test_trades_are_isolated_per_owner(pool, trades, owner):
    created = await trades.create_trade(TRADE)
    other = PostgresTradeRepository(pool, owner + "-other")

    assert await other.get_all_trades() == []
    assert await other.get_trade_by_id(created["id"]) is None
    assert await other.delete_trade(created["id"]) is False


async def test_update_merges_and_explicit_null_clears(trades):
    created = await trades.create_trade(TRADE)

    # Absent keys stay untouched, present keys overwrite, a JSON null clears.
    updated = await trades.update_trade(
        created["id"], {"price": 660.0, "notes": None}
    )

    assert updated["price"] == 660.0
    assert updated["notes"] is None
    assert updated["stopLoss"] == 640.0
    assert updated["id"] == created["id"]

    # An empty patch returns the current document unchanged.
    assert await trades.update_trade(created["id"], {}) == updated
    assert await trades.update_trade("missing-id", {"price": 1.0}) is None


async def test_supplied_id_is_kept_and_a_clash_gets_a_new_id(trades):
    created = await trades.create_trade({**TRADE, "id": "trade_1"})
    assert created["id"] == "trade_1"

    # Importing the same id twice must add a row, not overwrite the first.
    duplicate = await trades.create_trade({**TRADE, "id": "trade_1", "price": 1.0})
    assert duplicate["id"] != "trade_1"
    assert len(await trades.get_all_trades()) == 2
    assert (await trades.get_trade_by_id("trade_1"))["price"] == 650.0


async def test_reset_replaces_only_the_caller(pool, trades, owner):
    await trades.create_trade(TRADE)
    other = PostgresTradeRepository(pool, owner + "-other")
    await other.create_trade({**TRADE, "symbol": "WIPRO"})

    await trades.reset_trades(INITIAL_TRADES)

    assert len(await trades.get_all_trades()) == len(INITIAL_TRADES)
    kept = await trades.get_trade_by_id("trade_1")
    assert kept["symbol"] == "AAPL"
    assert [t["symbol"] for t in await other.get_all_trades()] == ["WIPRO"]


async def test_reset_assigns_ids_to_duplicates(trades):
    await trades.reset_trades([TRADE, {**TRADE, "price": 1.0}])

    all_trades = await trades.get_all_trades()
    assert len(all_trades) == 2
    assert len({t["id"] for t in all_trades}) == 2


async def test_delete_reports_whether_a_row_existed(trades):
    created = await trades.create_trade(TRADE)

    assert await trades.delete_trade(created["id"]) is True
    assert await trades.delete_trade(created["id"]) is False


# --- Tags -----------------------------------------------------------------

async def test_strategy_duplicates_are_case_insensitive(strategies):
    assert await strategies.add_strategy("  Breakout  ") is True
    assert await strategies.add_strategy("breakout") is False
    assert await strategies.add_strategy("   ") is False
    assert await strategies.get_all_strategies() == ["Breakout"]


async def test_delete_strategy_cascades_to_uncategorized(trades, strategies):
    await strategies.reset_strategies(DEFAULT_STRATEGIES)
    matching = await trades.create_trade(TRADE)
    untouched = await trades.create_trade({**TRADE, "strategy": "Gap Fill"})

    assert await strategies.delete_strategy("BREAKOUT") is True
    assert await strategies.delete_strategy("Breakout") is False

    assert (await trades.get_trade_by_id(matching["id"]))["strategy"] == "Uncategorized"
    assert (await trades.get_trade_by_id(untouched["id"]))["strategy"] == "Gap Fill"
    assert "Breakout" not in await strategies.get_all_strategies()


async def test_emotion_delete_cascades_to_neutral(trades, emotions):
    await emotions.reset_emotions(DEFAULT_EMOTIONS)
    created = await trades.create_trade(TRADE)

    assert await emotions.delete_emotion("disciplined") is True
    assert (await trades.get_trade_by_id(created["id"]))["emotion"] == "Neutral"


# --- Watchlists -----------------------------------------------------------

async def test_watchlist_upserts_one_row_per_owner(pool, owner):
    watchlist = PostgresWatchlistRepository(pool, owner)
    assert await watchlist.get_keys() == []

    await watchlist.set_keys(["NSE_EQ|INE062A01020"])
    await watchlist.set_keys(["NSE_EQ|INE160A01022", "NSE_EQ|INE467I01027"])

    assert await watchlist.get_keys() == [
        "NSE_EQ|INE160A01022",
        "NSE_EQ|INE467I01027",
    ]
    other = PostgresWatchlistRepository(pool, owner + "-other")
    assert await other.get_keys() == []


# --- Service --------------------------------------------------------------

async def test_journal_service_seeds_a_new_account_once(pool, owner):
    service = JournalService(
        PostgresTradeRepository(pool, owner),
        PostgresStrategyRepository(pool, owner),
        PostgresEmotionRepository(pool, owner),
    )

    overview = await service.get_journal_overview()
    assert len(overview["trades"]) == len(INITIAL_TRADES)
    assert overview["strategies"] == DEFAULT_STRATEGIES
    assert overview["emotions"] == DEFAULT_EMOTIONS

    # A second read is a no-op: seeding must not duplicate the journal.
    again = await service.get_journal_overview()
    assert len(again["trades"]) == len(INITIAL_TRADES)

    await service.reset_to_mock()
    assert len((await service.get_journal_overview())["trades"]) == len(INITIAL_TRADES)


async def test_pool_surfaces_an_unreachable_database():
    # Guards the deployment mistake of pasting the dashboard URL instead of
    # the connection string: the failure must surface, not hang the boot.
    with pytest.raises(Exception):
        await create_pool("postgresql://nobody@127.0.0.1:1/none")
