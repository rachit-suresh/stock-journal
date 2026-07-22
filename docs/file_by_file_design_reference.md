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
│   │   │   ├── emotions.py         # Dedicated REST endpoints for emotions CRUD
│   │   │   ├── journal.py          # Master journal overview, reset, & import fallback router
│   │   │   ├── prices.py           # Real-time price cache query router (with success: True contract)
│   │   │   ├── strategies.py       # Dedicated REST endpoints for strategies CRUD
│   │   │   └── trades.py           # Dedicated REST endpoints for trades CRUD
│   │   └── router.py               # Master APIRouter aggregator
│   ├── core/
│   │   ├── __init__.py             # Core package marker
│   │   ├── config.py               # Centralized Settings & environment parser
│   │   └── database.py             # Async Motor MongoDB connection manager (with active ping validation)
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
│   │   │   └── trade_repository.py   # In-memory implementation for isolated unit testing
│   │   └── mongo/
│   │       ├── __init__.py         # Mongo repos package marker
│   │       ├── emotion_repository.py # Async Motor MongoDB emotion store (with re.escape regex security)
│   │       ├── strategy_repository.py# Async Motor MongoDB strategy store (with re.escape regex security)
│   │       └── trade_repository.py   # Async Motor MongoDB trade store (with $or ID query matching)
│   ├── services/
│   │   ├── __init__.py             # Services package marker
│   │   └── journal_service.py      # Business logic orchestrator & DB auto-seeding
│   └── streaming/
│       ├── __init__.py             # Streaming package marker
│       ├── angel_one_streamer.py   # Angel One SmartAPI WebSocket 2.0 ticker engine
│       ├── base_streamer.py        # Abstract IMarketDataStreamer interface
│       ├── mock_streamer.py        # Mock random-walk market data streamer
│       └── price_cache.py          # Thread-safe in-memory price storage engine
├── docs/
│   ├── architecture.md             # HLD, LLD, Class Diagrams, Sequence Workflows, SOLID proofs
│   ├── design_decisions_and_tradeoffs.md # Executive design decisions & engineering tradeoffs
│   ├── file_by_file_design_reference.md  # Detailed reference manual (This document)
│   └── production_deployment_guide.md   # Deployment guide for Render, Vercel & MongoDB Atlas
├── static/
│   ├── app.js                      # DOM Event handlers, Chart.js renderings, & View management
│   ├── index.html                  # HTML5 semantic dashboard markup
│   ├── mockApi.js                  # Frontend market price polling engine
│   ├── mockData.js                 # Initial seed trade data fixtures
│   ├── state.js                    # Client StateManager & portfolio metrics calculator (RESTful calls)
│   └── styles.css                  # Custom CSS styling with dark glassmorphism design system
├── tests/
│   ├── __init__.py                 # Tests package marker
│   ├── test_api_endpoints.py       # FastAPI HTTP route integration test suite
│   ├── test_models.py              # Pydantic schema validation test suite
│   ├── test_price_cache.py         # Multi-threaded price cache concurrency test suite
│   └── test_repositories.py        # Repository CRUD & soft cascading update test suite
├── .gitignore                      # Git exclusion rules (.env, __pycache__, .pytest_cache)
├── main.py                         # FastAPI application entrypoint & Lifespan startup
├── requirements.txt                # Python package dependency manifest (logzero cleaned)
└── vercel.json                     # Vercel deployment specification & /api/* proxy rewrites
```

---

## 2. Core Configuration & Database Infrastructure Layer (`app/core/`)

### `app/core/config.py`

#### Class `Settings`
Parses and validates environment variables using standard Python `os.getenv` defaults.

- **Attributes**:
  - `PROJECT_NAME` (`str`): Application title (`"Stock Journal Monolith"`).
  - `VERSION` (`str`): Version identifier (`"2.0.0"`).
  - `API_KEY` (`str`): Angel One SmartAPI key (`SMART_API_KEY`).
  - `CLIENT_CODE` (`str`): Angel One Client Code (`SMART_CLIENT_CODE`).
  - `PASSWORD` (`str`): Angel One Trading Password (`SMART_PASSWORD`).
  - `TOTP_SECRET` (`str`): 2FA TOTP secret (`SMART_TOTP_SECRET`).
  - `MOCK_STREAMER` (`bool`): Boolean flag enabling mock simulation mode (`MOCK_STREAMER`).
  - `TOKENS_STR` (`str`): Comma-separated list of NSE tokens to stream (`TOKENS`).
  - `ALLOWED_ORIGINS_STR` (`str`): Comma-separated CORS whitelist origins (`ALLOWED_ORIGINS`).
  - `MONGO_URI` (`str`): MongoDB connection string (`MONGO_URI`, default: `mongodb://localhost:27017`).
  - `MONGO_DB_NAME` (`str`): Target database name (`MONGO_DB_NAME`, default: `stock_journal`).
- **Methods**:
  - `get_tokens() -> List[str]`: Splits `TOKENS_STR` by comma, strips whitespace, and returns cleaned token strings.
  - `get_allowed_origins() -> List[str]`: Parses `ALLOWED_ORIGINS_STR`. Returns `["*"]` if set to `"*"` or empty; otherwise returns split domain whitelist.
  - `has_smart_api_credentials() -> bool`: Returns `True` only if `API_KEY`, `CLIENT_CODE`, `PASSWORD`, and `TOTP_SECRET` are all non-empty strings.

---

### `app/core/database.py`

#### Class `DatabaseManager`
Manages the lifecycle of the asynchronous Motor MongoDB client (`AsyncIOMotorClient`).

- **Attributes**:
  - `client` (`Optional[AsyncIOMotorClient]`): Active Motor client instance or `None`.
  - `db` (`Optional[AsyncIOMotorDatabase]`): Target database handle or `None`.
- **Functions**:
  - `connect_to_mongo() -> None`: Initializes `AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)` and assigns `db = client[settings.MONGO_DB_NAME]`. Executes `await client.admin.command('ping')` to verify live server connectivity before logging success.
  - `close_mongo_connection() -> None`: Safely closes the active Motor client connection upon shutdown.
  - `get_database() -> AsyncIOMotorDatabase`: Returns the active `db` handle for FastAPI dependency injection.

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
  - `id` (`str`): Primary string key (maps to MongoDB `_id` string or `custom_id`).

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

### 4.2 MongoDB Motor Implementations (`app/repositories/mongo/`)

- **`MongoTradeRepository`**: Executes async Motor queries against the `trades` collection. Query methods (`get_trade_by_id`, `update_trade`, `delete_trade`) use `$or` conditions matching `_id` (if valid ObjectId) and `custom_id`. Consistently extracts and preserves string `id` attributes.
- **`MongoStrategyRepository`**: Executes async Motor queries against the `strategies` collection. Uses `re.escape()` on input names inside case-insensitive `$regex` queries to eliminate NoSQL regex injection vulnerabilities. When a strategy is deleted, executes `update_many` on `trades` setting affected strategy attributes to `"Uncategorized"`.
- **`MongoEmotionRepository`**: Executes async Motor queries against the `emotions` collection. Uses `re.escape()` on input names inside case-insensitive `$regex` queries to eliminate NoSQL regex injection vulnerabilities. When an emotion is deleted, executes `update_many` on `trades` setting affected emotion attributes to `"Neutral"`.

---

### 4.3 In-Memory Testing Implementations (`app/repositories/memory/`)

- **`MemoryTradeRepository`**, **`MemoryStrategyRepository`**, **`MemoryEmotionRepository`**: Pure Python memory implementations used by pytest to run lightning-fast integration tests without requiring an active MongoDB database.

---

## 5. Streaming Subsystem (`app/streaming/`)

- **`PriceCache`**: Thread-safe memory cache. `set_price(token, price)` locks `threading.Lock()` to write price; `get_batch_prices(tokens)` locks to fetch batch prices in nanoseconds.
- **`AngelOneSmartApiStreamer`**: Connects to Angel One WebSocket 2.0 using TOTP authentication, parses binary ticks, converts integer paise to Rupees (`ltp / 100.0`), and writes updates to `PriceCache`.
- **`MockMarketStreamer`**: Simulates real-time stock price movements using a random-walk algorithm ($\pm 0.4\%$) for Indian equity tokens (`3045`, `2885`, `11536`, `1594`, `3456`).

---

## 6. Service & API Layer (`app/services/` & `app/api/`)

- **`JournalService`**: Coordinates business logic and executes initial seed data loading if MongoDB collections are empty on first boot.
- **`app/api/endpoints/prices.py`**: Returns real-time token price dictionary formatted with `"success": True, "data": {...}, "timestamp": ...`.
- **`app/api/endpoints/trades.py`**: Dedicated RESTful handlers (`GET /api/trades`, `POST /api/trades`, `GET /api/trades/{id}`, `PUT /api/trades/{id}`, `DELETE /api/trades/{id}`).
- **`app/api/endpoints/strategies.py`**: Dedicated RESTful handlers (`GET /api/strategies`, `POST /api/strategies`, `DELETE /api/strategies/{name}`).
- **`app/api/endpoints/emotions.py`**: Dedicated RESTful handlers (`GET /api/emotions`, `POST /api/emotions`, `DELETE /api/emotions/{name}`).
- **`app/api/endpoints/journal.py`**: Overview, bulk reset, and bulk import endpoints with backwards-compatible fallbacks.
- **`app/api/router.py`**: Aggregates all endpoint routers into unified `api_router`.
- **`main.py`**: FastAPI entrypoint, lifespan startup manager, static file server, CORS middleware, and dynamic `$PORT` environment parser.

---

## 7. Client Frontend Dashboard (`static/`)

- **`static/state.js`**: `StateManager` class handling local state, metric calculations, and asynchronous RESTful API synchronization with backend (`/api/trades`, `/api/strategies`, `/api/emotions`). Free of undefined `notifyTabs()` ghost calls.
- **`static/app.js`**: DOM UI event listeners, view switcher (`dashboard`, `tradelog`, `strategies`), form submission handlers, and Chart.js equity/allocation chart rendering engine.
- **`static/mockApi.js`**: Background tick polling engine fetching `/api/prices` every 2.5s and notifying UI listeners.

---

## 8. Automated Test Suite (`tests/`)

- **`tests/test_models.py`**: Validates Pydantic schema validation rules.
- **`tests/test_price_cache.py`**: Tests thread-safety under multi-threaded concurrent write workloads.
- **`tests/test_repositories.py`**: Tests CRUD operations and cascading trade updates upon category deletion.
- **`tests/test_api_endpoints.py`**: Integration tests across all FastAPI HTTP endpoints using `TestClient`. Run via `python -m pytest -v`.
