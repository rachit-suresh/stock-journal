# File-by-File Design Reference & Code Architecture Guide

This reference document provides an exhaustive, granular breakdown of every single file, class, function, parameter signature, return type, and design decision across the entire **Stock Journal** codebase.

---

## 1. Project Directory Structure

```
stock-journal/
├── app/
│   ├── __init__.py                 # Python package marker
│   ├── api/
│   │   ├── __init__.py             # API package marker
│   │   ├── endpoints/
│   │   │   ├── __init__.py         # Endpoints package marker
│   │   │   ├── auth_config.py      # Public GET /auth/config (Supabase URL + anon key for the SPA)
│   │   │   ├── emotions.py         # Dedicated REST endpoints for emotions CRUD
│   │   │   ├── journal.py          # Master journal overview & bulk-import router (no reset route)
│   │   │   ├── prices.py           # Real-time price cache query router (with success: True contract)
│   │   │   ├── strategies.py       # Dedicated REST endpoints for strategies CRUD
│   │   │   └── trades.py           # Dedicated REST endpoints for trades CRUD
│   │   └── router.py               # Master APIRouter aggregator
│   ├── core/
│   │   ├── __init__.py             # Core package marker
│   │   ├── config.py               # Centralized Settings & environment parser
│   │   ├── database.py             # asyncpg pool lifecycle + jsonb codec + /health probe
│   │   ├── limits.py               # Per-user caps and sliding-window mutation rate limit
│   │   ├── schema.py               # Idempotent Postgres DDL: 4 tables, indexes, RLS
│   │   └── security.py             # Supabase JWT verification (JWKS or legacy HS256) + get_current_user
│   ├── models/
│   │   ├── __init__.py             # Models package marker
│   │   ├── emotion.py              # Pydantic v2 schemas for emotion entities
│   │   ├── strategy.py             # Pydantic v2 schemas for strategy entities
│   │   └── trade.py                # Pydantic v2 schemas with field validators & HTML sanitization
│   ├── repositories/
│   │   ├── __init__.py             # Repositories package marker
│   │   ├── interfaces/
│   │   │   ├── __init__.py         # Interfaces package marker
│   │   │   ├── emotion_repository.py # Abstract Base Class contract for emotions persistence
│   │   │   ├── strategy_repository.py# Abstract Base Class contract for strategies persistence
│   │   │   └── trade_repository.py   # Abstract Base Class contract for trades persistence
│   │   ├── memory/
│   │   │   ├── __init__.py         # Memory repos package marker
│   │   │   ├── emotion_repository.py # In-memory implementation for isolated unit testing
│   │   │   ├── strategy_repository.py# In-memory implementation for isolated unit testing
│   │   │   ├── trade_repository.py   # In-memory implementation for isolated unit testing
│   │   │   └── watchlist_repository.py # In-memory watchlist (test double)
│   │   └── postgres/
│   │       ├── __init__.py         # Postgres repos package marker
│   │       ├── emotion_repository.py # Emotion tags (delegates to TagStore)
│   │       ├── strategy_repository.py# Strategy tags (delegates to TagStore)
│   │       ├── tag_store.py        # Shared tag SQL: add/delete/reset + trade cascade
│   │       ├── trade_repository.py   # jsonb trade storage, owner-scoped, transactional reset
│   │       └── watchlist_repository.py # One row per owner (text[] keys)
│   ├── services/
│   │   ├── __init__.py             # Services package marker
│   │   └── journal_service.py      # Business logic orchestrator & tag-only seeding
│   └── streaming/
│       ├── __init__.py             # Streaming package marker
│       ├── upstox_streamer.py      # Upstox market data feed v3 WebSocket ticker engine
│       ├── base_streamer.py        # Abstract IMarketDataStreamer interface
│       ├── mock_streamer.py        # Mock random-walk market data streamer
│       └── price_cache.py          # Thread-safe in-memory price storage with staleness metadata
├── docs/
│   ├── architecture.md             # HLD, LLD, Class Diagrams, Sequence Workflows, SOLID proofs
│   ├── design_decisions_and_tradeoffs.md # Executive design decisions & engineering tradeoffs
│   ├── file_by_file_design_reference.md  # Detailed reference manual (This document)
│   └── production_deployment_guide.md   # Deployment guide for Render, Vercel & Supabase
├── static/
│   ├── app.js                      # DOM Event handlers, Chart.js renderings, INR formatting, & View management
│   ├── api.js                      # Single fetch entry point: base URL + bearer token + 401 handling
│   ├── auth.js                     # Supabase Auth gate (email + password), session and token access
│   ├── index.html                  # HTML5 semantic dashboard markup + sign-in gate + walkthrough modal
│   ├── marketFeed.js               # Instrument-key driven price polling engine (watchlist + positions)
│   ├── onboarding.js               # 6-step walkthrough behind the "Walkthrough & Help" button
│   ├── state.js                    # Client StateManager & portfolio metrics calculator (RESTful calls)
│   └── styles.css                  # Custom CSS styling with dark glassmorphism design system
├── tests/
│   ├── __init__.py                 # Tests package marker
│   ├── conftest.py                 # In-memory owner fixtures (api, anon_client)
│   ├── test_api_endpoints.py       # FastAPI HTTP route integration test suite
│   ├── test_auth.py                # JWT verification, tenancy, caps and rate-limit tests
│   ├── test_models.py              # Pydantic schema validation test suite
│   ├── test_market_data.py         # Upstox feed parsing & price-cache tick tests
│   ├── test_postgres.py            # Real-Postgres repository tests (pgserver or TEST_DATABASE_URL)
│   ├── test_price_cache.py         # Multi-threaded price cache concurrency test suite
│   ├── test_repositories.py        # Repository CRUD & soft cascading update test suite
│   └── test_subscriptions.py       # Subscription registry diff/prune tests
├── .gitignore                      # Git exclusion rules (.env, __pycache__, .pytest_cache, .pgtest)
├── main.py                         # FastAPI application entrypoint & Lifespan startup
├── pytest.ini                      # Pytest configuration (`asyncio_mode = auto`)
├── requirements.txt                # Production dependency manifest (asyncpg, no motor/pymongo)
├── requirements-dev.txt            # `-r requirements.txt` + pgserver, for the local Postgres tests
└── vercel.json                     # Vercel deployment spec & /api/* + /auth/config proxy rewrites
```

---

## 2. Core Configuration & Database Infrastructure Layer (`app/core/`)

### `app/core/config.py`

#### Class `Settings`
Parses and validates environment variables using standard Python `os.getenv` defaults.

- **Attributes**:
  - `PROJECT_NAME` (`str`): Application title (`"Stock Journal Monolith"`).
  - `VERSION` (`str`): Version identifier (`"2.0.0"`).
  - `UPSTOX_ACCESS_TOKEN` (`str`): Upstox Analytics Access Token (read-only, one-year validity, covers Market Data + Streaming) (`UPSTOX_ACCESS_TOKEN`).
  - `MOCK_STREAMER` (`bool`): Boolean flag enabling mock simulation mode (`MOCK_STREAMER`).
  - `TOKENS_STR` (`str`): Comma-separated list of Upstox instrument keys, e.g. `NSE_EQ|INE062A01020` (`TOKENS`).
  - `PRICE_MAX_AGE_SECONDS` (`float`): Age after which a cached tick is reported as stale (`PRICE_MAX_AGE_SECONDS`, default `30`).
  - `ALLOWED_ORIGINS_STR` (`str`): Comma-separated CORS whitelist origins (`ALLOWED_ORIGINS`).
  - `DATABASE_URL` (`str`): Postgres connection string - the Supabase **session pooler** URI in production (`DATABASE_URL`).
  - `SUPABASE_URL` (`str`): Supabase project URL, trailing slash stripped (`SUPABASE_URL`). Also the JWT issuer prefix.
  - `SUPABASE_ANON_KEY` (`str`): Public anon/publishable key served by `/auth/config` (`SUPABASE_ANON_KEY`, falling back to `SUPABASE_PUBLISHABLE_KEY`).
  - `SUPABASE_JWT_SECRET` (`str`): Only for projects still signing tokens with the legacy HS256 secret (`SUPABASE_JWT_SECRET`).
  - `ENV`, `AUTH_DISABLED`, `DEV_USER_ID`: mode guards (see SPEC-AUTH-5).
  - The abuse limits: `MUTATION_RATE_LIMIT_PER_MINUTE`, `MAX_TRADES_PER_USER`, `MAX_STRATEGIES_PER_USER`, `MAX_EMOTIONS_PER_USER`, `MAX_WATCHLIST_KEYS`, `WATCHLIST_TTL_SECONDS`.
- **Methods**:
  - `get_tokens() -> List[str]`: Splits `TOKENS_STR` by comma, strips whitespace, and returns cleaned token strings.
  - `get_allowed_origins() -> List[str]`: Parses `ALLOWED_ORIGINS_STR`. Returns `["*"]` if set to `"*"` or empty; otherwise returns split domain whitelist.
  - `has_upstox_credentials() -> bool`: Returns `True` when `UPSTOX_ACCESS_TOKEN` is non-empty; drives mock-vs-live streamer selection.
  - `supabase_issuer() -> str`: `f"{SUPABASE_URL}/auth/v1"` - the exact `iss` claim Supabase stamps on access tokens (empty when the URL is unset).
  - `auth_mode() -> str`: `"dev-bypass"` or `"supabase"`, reported by `/health`.
  - `validate_auth_config() -> None`: raises when `AUTH_DISABLED` meets `ENV=production`, and logs (without raising) a missing `SUPABASE_URL` / `SUPABASE_ANON_KEY` so the process still boots and fails closed with `401`s.

---

### `app/core/database.py`

#### Class `DatabaseManager`
Holds the process-wide asyncpg pool.

- **Attributes**: `pool` (`Optional[asyncpg.Pool]`).
- **Functions**:
  - `create_pool(dsn) -> asyncpg.Pool`: `min_size=1`, `max_size=5`, `command_timeout=30`, and **`statement_cache_size=0`** because Supabase's pooler cannot keep server-side prepared statements. Every connection gets a `jsonb` codec, so repositories pass plain dicts.
  - `connect_to_database() -> None`: opens the pool, then runs `ensure_schema()`. A failure is logged and swallowed so the process still boots and `/health` can report `database: unavailable` (data routes then answer `503`).
  - `close_database_connection() -> None`: closes the pool on shutdown.
  - `get_pool() -> asyncpg.Pool`: FastAPI dependency; raises `503` when the pool is missing.
  - `database_status() -> str`: `"ok"` when `SELECT 1` succeeds, else `"unavailable"` (used by `/health`).

### `app/core/schema.py`

`SCHEMA_SQL` is one idempotent script (`CREATE TABLE IF NOT EXISTS`, `CREATE ... INDEX IF NOT EXISTS`, `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`); `ensure_schema(pool)` runs it inside a transaction holding `pg_advisory_xact_lock(...)`, so two instances booting together cannot race. Full DDL in `architecture.md` §5.

### `app/core/security.py`

- **`UserContext`** (frozen dataclass): `user_id`, `email`, `authenticated`.
- **`verify_session_token(token) -> dict`**: derives the algorithm from the token header, then verifies with **only** that family - `HS256` against `SUPABASE_JWT_SECRET`, `RS256`/`ES256` against the cached JWKS at `<issuer>/.well-known/jwks.json` - and requires `exp`, `iss`, `sub` and `aud=authenticated`. An HS256 token is never checked against a public JWKS key (algorithm confusion).
- **`get_current_user(credentials) -> UserContext`**: `AUTH_DISABLED` returns the fixed `DEV_USER_ID` (refused in production); otherwise a missing bearer token or a failed verification is a `401` with `WWW-Authenticate: Bearer`.

### `app/core/limits.py`

`enforce_cap(count, cap, label)` raises `400` at an owner's cap; `mutation_rate_limit` is a per-`(user_id, ip)` sliding window over POST/PUT/DELETE returning `429` + `Retry-After`. Counters are process-local by design.

---

## 3. Pydantic Domain Model Layer (`app/models/`)

### `app/models/trade.py`

- **Class `TradeCreate(BaseModel)`**:
  - `symbol` (`str`): Uppercase ticker symbol (e.g., `"SBIN"`). Sanitized to uppercase stripped string via `@field_validator("symbol")`.
  - `side` (`str`): `"BUY"` or `"SELL"`. Validated via `@field_validator("side")`.
  - `price` (`float`): Execution price. Must satisfy `gt=0`.
  - `stopLoss` (`Optional[float]`): Optional stop loss price.
  - `shares` (`int`): Quantity traded. Must satisfy `gt=0`.
  - `pfMatrix` (`Optional[float]`): Portfolio risk/reward score matrix.
  - `rsMatrix` (`Optional[float]`): Relative strength score matrix.
  - `xPercentage` (`Optional[float]`): Position size percentage.
  - `strategy` (`str`): Tagged strategy name (default: `"Uncategorized"`). Sanitized via `html.escape()`.
  - `emotion` (`str`): Tagged emotion mindset (default: `"Neutral"`). Sanitized via `html.escape()`.
  - `mistakes` (`List[str]`): List of mistake tags (default: `["None"]`).
  - `notes` (`Optional[str]`): Trade analysis notes. Sanitized via `html.escape()`.
  - `date` (`Optional[str]`): ISO timestamp generated via `datetime.now(timezone.utc).isoformat()`.

- **Class `TradeUpdate(BaseModel)`**:
  - All fields made optional to support partial updates (`PUT`). Includes identical `@field_validator` hooks for `symbol`, `side`, and text fields.

- **Class `TradeResponse(TradeCreate)`**:
  - `id` (`str`): Public trade id (`trade_1` from an import, otherwise a generated uuid4 hex).

---

### `app/models/strategy.py`

- **Class `StrategyCreate(BaseModel)`**:
  - `name` (`str`): Strategy identifier. Must satisfy `min_length=1`.

---

### `app/models/emotion.py`

- **Class `EmotionCreate(BaseModel)`**:
  - `name` (`str`): Emotion identifier. Must satisfy `min_length=1`.

---

## 4. Repository Abstraction Layer (`app/repositories/`)

### 4.1 Interface Contracts (`app/repositories/interfaces/`)

- **`ITradeRepository(ABC)`**: Defines `get_all_trades()`, `get_trade_by_id(id)`, `create_trade(trade)`, `update_trade(id, update)`, `delete_trade(id)`, `reset_trades(trades)`.
- **`IStrategyRepository(ABC)`**: Defines `get_all_strategies()`, `add_strategy(name)`, `delete_strategy(name)`, `reset_strategies(strategies)`.
- **`IEmotionRepository(ABC)`**: Defines `get_all_emotions()`, `add_emotion(name)`, `delete_emotion(name)`, `reset_emotions(emotions)`.

---

### 4.2 Postgres Implementations (`app/repositories/postgres/`)

- **`PostgresTradeRepository`**: `trades(owner_id, id, seq, data jsonb)`. Reads run `ORDER BY seq`; `create_trade` keeps a supplied `id`, generates a uuid4 hex otherwise, and retries with a fresh id when the id already exists (`ON CONFLICT DO NOTHING`), so an import can never overwrite a row. `update_trade` merges with `data || $patch` (absent keys untouched, an explicit `null` clears). `reset_trades` deletes and re-inserts in one transaction.
- **`TagStore`** (`tag_store.py`): the shared SQL for both tag tables - `all`, `add` (unique `(owner_id, lower(name))` + `ON CONFLICT DO NOTHING`, so a duplicate is a `400` rather than a `500`), `delete` (deletes case-insensitively, then re-assigns this owner's trades to `Uncategorized` / `Neutral` in the same transaction) and `reset`. Table and trade-field names come from constants, never from input.
- **`PostgresStrategyRepository`** / **`PostgresEmotionRepository`**: thin wrappers over `TagStore` with the cascade target baked in.
- **`PostgresWatchlistRepository`**: one row per owner; `get_keys` returns `[]` when no row exists, `set_keys` upserts `(keys, updated_at)`.

---

### 4.3 In-Memory Testing Implementations (`app/repositories/memory/`)

- **`MemoryTradeRepository`**, **`MemoryStrategyRepository`**, **`MemoryEmotionRepository`**, **`MemoryWatchlistRepository`**: Pure Python implementations used by pytest to run fast API tests without a database. The API tests override the repository factories with these; `test_postgres.py` exercises the real SQL against a throwaway cluster.

---

## 5. Streaming Subsystem (`app/streaming/`)

- **`PriceCache`**: Thread-safe memory cache keyed by instrument key. `set_price(token, price)` stores `(ltp, timestamp)` under `threading.Lock()`; `get_batch_prices(tokens)` returns the last known LTP (default `100.0` for unknown keys); `get_batch_meta(tokens)` returns `as_of`/`stale` per key against `PRICE_MAX_AGE_SECONDS`.
- **`UpstoxMarketStreamer`**: Wraps `upstox_client.MarketDataStreamerV3`; subscribes `TOKENS` in `"ltpc"` mode on open, decodes `{"type": "live_feed", "feeds": {...}}` messages, ignores `market_info`, and writes LTPs to `PriceCache`. The SDK import is lazy so mock mode runs without it.
- **`MockMarketStreamer`**: Simulates real-time price movements using a random-walk algorithm ($\pm 0.4\%$) for the five default instrument keys (`SBIN` 650, `PNB` 80, `TCS` 3500, `INFY` 1500, `WIPRO` 450). A key it does not recognise gets no tick at all, so an unquoted instrument renders `—` exactly as in live mode instead of an invented `100.0`.

---

## 6. Service & API Layer (`app/services/` & `app/api/`)

- **`JournalService`**: Coordinates business logic and seeds **only the default strategy/emotion taxonomy** when the caller's tag tables are empty on first `GET /api/journal` (seeding is a side effect of the first read, never of startup). It never creates trades, and there is no reset-to-demo method any more.
- **`app/api/endpoints/prices.py`**: Returns the cached price dictionary as `{"success": True, "data": {instrument_key: ltp}, "meta": {instrument_key: {as_of, stale}}, "timestamp": ...}`.
- **`app/api/endpoints/trades.py`**: Dedicated RESTful handlers (`GET /api/trades`, `POST /api/trades`, `GET /api/trades/{id}`, `PUT /api/trades/{id}`, `DELETE /api/trades/{id}`).
- **`app/api/endpoints/strategies.py`**: Dedicated RESTful handlers (`GET /api/strategies`, `POST /api/strategies`, `DELETE /api/strategies/{name}`).
- **`app/api/endpoints/emotions.py`**: Dedicated RESTful handlers (`GET /api/emotions`, `POST /api/emotions`, `DELETE /api/emotions/{name}`).
- **`app/api/endpoints/journal.py`**: Overview (`GET`) and bulk import (`POST`) endpoints. Legacy query-param compat routes were removed (GAP-3b) and `POST /journal/reset` was deleted in v1.6, so a live journal cannot be restored to sample data.
- **`app/models/responses.py`**: Pydantic response envelopes (`DataResponse[T]`, `MessageResponse`, `PricesResponse`, `JournalResponse`) wired as `response_model` on every route (GAP-8b).
- **`app/api/endpoints/auth_config.py`**: Public `GET /auth/config` → `{"provider": "supabase", "url", "anonKey"}`, or `{"provider": "none"}` while `AUTH_DISABLED` is on. This is what lets the SPA change environments with no code edit.
- **`app/api/endpoints/health.py`**: Public `GET /health` → status, `env`, `auth`, `database`, `streamer`, `prices_fresh`.
- **`app/api/router.py`**: Aggregates all endpoint routers into unified `api_router`.
- **`main.py`**: FastAPI entrypoint, lifespan startup manager, static file server, CORS middleware, and dynamic `$PORT` environment parser.

---

## 7. Client Frontend Dashboard (`static/`)

- **`static/auth.js`**: Supabase Auth gate. Reads `window.SUPABASE_URL`/`window.SUPABASE_ANON_KEY` or falls back to `GET /auth/config`, dynamically imports supabase-js v2 from jsDelivr, then renders an email + password form (with a "Create an account" toggle). Exports `authReady`, `authMode`, `authSuspended`, `getAuthToken` (refreshes a token inside 30 s of expiry), `clearLocalJournalKeys`, `handleUnauthorized`, `signOut`, `currentUserEmail`; a `401` from the API signs out with `scope: 'local'` and returns to the gate.
- **`static/api.js`**: `apiFetch(path, options)` - the only place a request is made: waits for `authReady`, attaches the bearer token, short-circuits while `authSuspended()`, and routes `401`s through `handleUnauthorized`.
- **`static/state.js`**: `StateManager` class handling local state, metric calculations, and asynchronous RESTful API synchronization with backend (`/api/trades`, `/api/strategies`, `/api/emotions`). It starts from `[]` (no bundled sample trades), exposes `getSymbolKeys()` so positions can be quoted, and turns any non-2xx write into a visible `sj:sync-error` toast. There is no starting capital (v1.7): `portfolioValue` = Σ |shares| × price starts at `₹0.00`, an unpriced position is held at cost and counted in `unpricedValueCount`, and the `equityCurve` is cumulative **realized** P&L from zero. `exportData()` writes format `1.3`; `importData()` still accepts `1.2` payloads and ignores their `startingBalance`.
- **`static/app.js`**: DOM UI event listeners, view switcher (`dashboard`, `tradelog`, `strategies`), form submission handlers, INR money/chart formatting, empty states with a next action, the Help-button walkthrough wiring, and Chart.js rendering for the "Portfolio Value" / "Cumulative Realized P&L" and asset-allocation charts. Metric captions are computed, not static: the first card names positions valued at cost, the unrealized card names positions it had to exclude.
- **`static/marketFeed.js`**: Background tick polling engine fetching `/api/prices` every 2.5s for the account's own instrument keys (watchlist ∪ position keys). Skips `meta.as_of === null` so the `100.0` placeholder is never painted, stays idle with no keys, and notifies UI listeners.
- **`static/onboarding.js`**: `mountTour()` renders the 6-step walkthrough (add stocks → record a trade → tag psychology → review → feed badge) with Next/Back/Skip, progress dots and two action buttons. Opened only by the sidebar "Walkthrough & Help" button - no first-run auto-open, no seen flag, no storage.

---

## 8. Automated Test Suite (`tests/`)

- **`tests/test_models.py`**: Validates Pydantic schema validation rules.
- **`tests/test_price_cache.py`**: Tests thread-safety under multi-threaded concurrent write workloads.
- **`tests/test_repositories.py`**: Tests CRUD operations and cascading trade updates upon category deletion (in-memory doubles).
- **`tests/test_postgres.py`**: The same contracts against a real PostgreSQL (started with the `pgserver` package, or `TEST_DATABASE_URL`): jsonb merge + null-clear, id preservation and clash handling, transactional reset isolation, `ON CONFLICT` de-duplication, cascade updates, watchlist upsert, RLS enabled with zero policies, and a `JournalService` pass that seeds tags but never trades.
- **`tests/test_api_endpoints.py`**: Integration tests across all FastAPI HTTP endpoints using `TestClient`. Run via `python -m pytest -v`.
