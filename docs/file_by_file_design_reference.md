# Complete File-by-File, Class-by-Class & Function-by-Function Design Reference

This document provides an exhaustive, granular design specification covering **every single file, class, function, method signature, data model, and architectural design decision** across the entire backend application codebase.

---

## Table of Contents
1. [Application Entrypoint (`main.py`)](#1-application-entrypoint-mainpy)
2. [Core Infrastructure Module (`app/core/`)](#2-core-infrastructure-module-appcore)
   - [`app/core/config.py`](#appcoreconfigpy)
   - [`app/core/database.py`](#appcoredatabasepy)
3. [Domain Models & Schemas (`app/models/`)](#3-domain-models--schemas-appmodels)
   - [`app/models/trade.py`](#appmodelstradepy)
   - [`app/models/strategy.py`](#appmodelsstrategypy)
   - [`app/models/emotion.py`](#appmodelsemotionpy)
4. [Persistence Layer & Interfaces (`app/repositories/`)](#4-persistence-layer--interfaces-apprepositories)
   - [Abstract Interfaces (`app/repositories/interfaces/`)](#abstract-interfaces-apprepositoriesinterfaces)
   - [MongoDB Concrete Implementations (`app/repositories/mongo/`)](#mongodb-concrete-implementations-apprepositoriesmongo)
5. [Business Logic & Service Layer (`app/services/`)](#5-business-logic--service-layer-appservices)
   - [`app/services/journal_service.py`](#appservicesjournalservicepy)
6. [Market Streaming & Real-Time Ingestion (`app/streaming/`)](#6-market-streaming--real-time-ingestion-appstreaming)
   - [`app/streaming/price_cache.py`](#appstreamingpricecachepy)
   - [`app/streaming/base_streamer.py`](#appstreamingbasestreamerpy)
   - [`app/streaming/angel_one_streamer.py`](#appstreamingangelonestreamerpy)
   - [`app/streaming/mock_streamer.py`](#appstreamingmockstreamerpy)
7. [API Endpoints & Routing Layer (`app/api/`)](#7-api-endpoints--routing-layer-appapi)
   - [`app/api/router.py`](#appapirouterpy)
   - [`app/api/endpoints/prices.py`](#appapiendpointspricespy)
   - [`app/api/endpoints/trades.py`](#appapiendpointstradespy)
   - [`app/api/endpoints/strategies.py`](#appapiendpointsstrategiespy)
   - [`app/api/endpoints/emotions.py`](#appapiendpointsemotionspy)
   - [`app/api/endpoints/journal.py`](#appapiendpointsjournalpy)

---

## 1. Application Entrypoint (`main.py`)

### File Overview
- **Path**: `main.py`
- **Purpose**: Serves as the single executable entrypoint for the Uvicorn ASGI server. Assembles the FastAPI application instance, configures CORS middleware, registers lifetime startup/shutdown handlers, mounts the master API router, and static asset file server.

### Detailed Design & Functions

#### `start_streamer_daemon()`
- **Signature**: `def start_streamer_daemon() -> None`
- **Design Rationale**: Instantiates and launches the real-time market data streaming subsystem inside a background OS daemon thread (`daemon=True`). Running streamer operations in a separate thread prevents long-running WebSocket blocking calls from halting the asyncio event loop.
- **Workflow & Exception Policy**:
  1. Inspects `settings.MOCK_STREAMER` and `settings.has_smart_api_credentials()`.
  2. If credentials exist and mock mode is `False`, instantiates `AngelOneSmartApiStreamer`. Otherwise, falls back to `MockMarketStreamer`.
  3. Encloses execution in an infinite `while True` reconnect loop. If a network socket drop or session timeout occurs, catches the exception, logs an error, sleeps for 10 seconds, and automatically reconnects.

#### `lifespan(app: FastAPI)`
- **Signature**: `@asynccontextmanager async def lifespan(app: FastAPI)`
- **Design Rationale**: Replaces deprecated FastAPI `@app.on_event("startup")` and `@app.on_event("shutdown")` triggers with a modern, structured async context manager lifecycle handler.
- **Workflow**:
  - **Startup**: Invokes `await connect_to_mongo()` to establish Motor MongoDB connection pools, then invokes `start_streamer_daemon()`.
  - **Yield**: Hands control over to the FastAPI request pipeline.
  - **Shutdown**: On server stop signal (SIGTERM/SIGINT), gracefully calls `await close_mongo_connection()`.

#### FastAPI Application Setup
- **Config**: Instantiates `app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)`.
- **CORS Middleware**: Adds `CORSMiddleware` with `allow_origins=["*"]`, enabling smooth integration during development and multi-domain deployments.
- **Static Mounting**: `app.mount("/", StaticFiles(directory="static", html=True), name="static")` mounted at the root path *after* API routes, ensuring `/api/*` requests take precedence over static HTML files.

---

## 2. Core Infrastructure Module (`app/core/`)

### `app/core/config.py`

#### Purpose
Centralized environment configuration management using `python-dotenv`. Ensures typed settings without scattering `os.getenv()` calls throughout business logic.

#### Class `Settings`
- **Fields**:
  - `PROJECT_NAME`: `str = "Stock Journal Monolith"`
  - `VERSION`: `str = "2.0.0"`
  - `API_KEY`: `str` (from `SMART_API_KEY`)
  - `CLIENT_CODE`: `str` (from `SMART_CLIENT_CODE`)
  - `PASSWORD`: `str` (from `SMART_PASSWORD`)
  - `TOTP_SECRET`: `str` (from `SMART_TOTP_SECRET`)
  - `MOCK_STREAMER`: `bool` (parsed from `MOCK_STREAMER` env var, defaults to `False`)
  - `TOKENS_STR`: `str` (comma-separated token list, defaults to `"3045,2885,11536,1594,3456"`)
  - `MONGO_URI`: `str` (defaults to `"mongodb://localhost:27017"`)
  - `MONGO_DB_NAME`: `str` (defaults to `"stock_journal"`)
- **Methods**:
  - `get_tokens() -> list[str]`: Splits `TOKENS_STR` by commas, strips whitespace, and returns a clean token array.
  - `has_smart_api_credentials() -> bool`: Returns `True` if `API_KEY`, `CLIENT_CODE`, `PASSWORD`, and `TOTP_SECRET` are all populated.

---

### `app/core/database.py`

#### Purpose
Manages the singleton `AsyncIOMotorClient` instance and MongoDB database reference using Motor (official async driver for MongoDB).

#### Class `DatabaseManager`
- **Attributes**: `client: AsyncIOMotorClient`, `db: AsyncIOMotorDatabase`.

#### Functions
- `connect_to_mongo() -> None`: Asynchronously initializes `AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=2000)` and selects database `settings.MONGO_DB_NAME`.
- `close_mongo_connection() -> None`: Closes open MongoDB socket pools cleanly during application shutdown.
- `get_database() -> AsyncIOMotorDatabase`: Returns `db_manager.db` for FastAPI Dependency Injection (`Depends(get_database)`).

---

## 3. Domain Models & Schemas (`app/models/`)

### `app/models/trade.py`

#### Pydantic Schemas for Trade Domain

1. **`TradeCreate(BaseModel)`**:
   - `symbol: str` (Required, e.g. `"SBIN"`)
   - `side: str` (Required, `"BUY"` or `"SELL"`)
   - `price: float` (Required, `gt=0`)
   - `stopLoss: Optional[float]` (Optional level)
   - `shares: int` (Required, `gt=0`)
   - `pfMatrix: Optional[float]` (Optional profit factor ratio)
   - `rsMatrix: Optional[float]` (Optional relative strength ratio)
   - `xPercentage: Optional[float]` (Optional risk allocation %)
   - `strategy: str` (Default `"Uncategorized"`)
   - `emotion: str` (Default `"Neutral"`)
   - `mistakes: List[str]` (Default `["None"]`)
   - `notes: Optional[str]` (Default `""`)
   - `date: Optional[str]` (Default ISO string timestamp)

2. **`TradeUpdate(BaseModel)`**:
   - Mirrors fields of `TradeCreate` with all fields marked `Optional`, allowing partial updates via HTTP `PUT` requests.

3. **`TradeResponse(TradeCreate)`**:
   - `id: str = Field(..., alias="id")`
   - Maps internal MongoDB `_id` / `custom_id` strings cleanly for JSON responses.

---

### `app/models/strategy.py` & `app/models/emotion.py`

#### `StrategyCreate` & `StrategyResponse`
- `StrategyCreate`: `name: str` (Validation: `min_length=1`).
- `StrategyResponse`: Inherits `StrategyCreate`, includes `id: str`.

#### `EmotionCreate` & `EmotionResponse`
- `EmotionCreate`: `name: str` (Validation: `min_length=1`).
- `EmotionResponse`: Inherits `EmotionCreate`, includes `id: str`.

---

## 4. Persistence Layer & Interfaces (`app/repositories/`)

### Abstract Interfaces (`app/repositories/interfaces/`)

Using Python's `abc.ABC` module, these files enforce **Dependency Inversion (DIP)**.

#### 1. `ITradeRepository` (`app/repositories/interfaces/trade_repository.py`)
- `async def get_all_trades(self) -> List[dict]`
- `async def get_trade_by_id(self, trade_id: str) -> Optional[dict]`
- `async def create_trade(self, trade: dict) -> dict`
- `async def update_trade(self, trade_id: str, trade_update: dict) -> Optional[dict]`
- `async def delete_trade(self, trade_id: str) -> bool`
- `async def reset_trades(self, trades: List[dict]) -> None`

#### 2. `IStrategyRepository` (`app/repositories/interfaces/strategy_repository.py`)
- `async def get_all_strategies(self) -> List[str]`
- `async def add_strategy(self, name: str) -> bool`
- `async def delete_strategy(self, name: str) -> bool`
- `async def reset_strategies(self, strategies: List[str]) -> None`

#### 3. `IEmotionRepository` (`app/repositories/interfaces/emotion_repository.py`)
- `async def get_all_emotions(self) -> List[str]`
- `async def add_emotion(self, name: str) -> bool`
- `async def delete_emotion(self, name: str) -> bool`
- `async def reset_emotions(self, emotions: List[str]) -> None`

---

### MongoDB Concrete Implementations (`app/repositories/mongo/`)

#### Class `MongoTradeRepository(ITradeRepository)`
- **Collection**: `db["trades"]`
- **Method Logic**:
  - `get_all_trades()`: Queries `find({})`, converts MongoDB `_id` `ObjectId` to `str`, returns document list.
  - `get_trade_by_id(trade_id)`: Checks if `trade_id` is valid `ObjectId` or custom string, returns matched document.
  - `create_trade(trade)`: Inserts document into MongoDB `trades` collection.
  - `update_trade(trade_id, trade_update)`: Executes `$set` query for non-None fields.
  - `delete_trade(trade_id)`: Performs `delete_one`.
  - `reset_trades(trades)`: Empties `trades` collection via `delete_many({})` and bulk inserts new items via `insert_many`.

#### Class `MongoStrategyRepository(IStrategyRepository)`
- **Collection**: `db["strategies"]` and `db["trades"]`
- **Method Logic**:
  - `add_strategy(name)`: Case-insensitive `$regex` check to prevent duplicates.
  - `delete_strategy(name)`: Removes strategy document, then invokes `update_many` on `trades` collection to automatically reassign linked trades to `"Uncategorized"`.

#### Class `MongoEmotionRepository(IEmotionRepository)`
- **Collection**: `db["emotions"]` and `db["trades"]`
- **Method Logic**:
  - `add_emotion(name)`: Case-insensitive `$regex` check to prevent duplicates.
  - `delete_emotion(name)`: Removes emotion document, then invokes `update_many` on `trades` collection to automatically reassign linked trades to `"Neutral"`.

---

## 5. Business Logic & Service Layer (`app/services/`)

### `app/services/journal_service.py`

#### Purpose
Orchestrates business logic workflows and first-time data seeding. Depends strictly on repository interfaces (`ITradeRepository`, `IStrategyRepository`, `IEmotionRepository`), achieving true decoupled application design.

#### Key Methods
- `seed_if_empty()`: Asynchronously checks if collections are empty. If empty, seeds initial default strategies (`Breakout`, `Pullback Support`, etc.), default emotions (`Disciplined`, `Confident`, etc.), and 9 sample trade records.
- `get_journal_overview() -> Dict[str, Any]`: Calls `seed_if_empty()`, then gathers all trades, strategies, and emotions in a unified dictionary payload.
- `add_trade()`, `update_trade()`, `delete_trade()`, `add_strategy()`, `delete_strategy()`, `add_emotion()`, `delete_emotion()`: Delegates CRUD calls to injected interface instances.
- `reset_to_mock()`: Re-populates initial sample dataset across all collections.

---

## 6. Market Streaming & Real-Time Ingestion (`app/streaming/`)

### `app/streaming/price_cache.py`

#### Class `PriceCache`
- **Thread Safety**: Encapsulates `_prices: Dict[str, float]` behind `threading.Lock()`.
- **Methods**:
  - `set_price(token: str, ltp: float)`: Updates tick price safely under lock.
  - `get_price(token: str, default: float = 100.0) -> float`: Reads single tick price.
  - `get_batch_prices(tokens: list[str]) -> Dict[str, float]`: Reads batch tick prices in a single locked block.

---

### `app/streaming/base_streamer.py`

#### Interface `IMarketDataStreamer(ABC)`
- `abstractmethod def authenticate(self) -> bool`
- `abstractmethod def connect_and_stream(self, tokens: list[str]) -> None`
- `abstractmethod def on_tick_received(self, token: str, ltp: float) -> None`

---

### `app/streaming/angel_one_streamer.py`

#### Class `AngelOneSmartApiStreamer(IMarketDataStreamer)`
- **Authentication**: Uses `SmartConnect` and `pyotp.TOTP` to generate session JWT token and feed token.
- **Tick Stream Parsing**: Initializes `SmartWebSocketV2`. When binary WebSocket ticks arrive in `on_data`, parses `last_traded_price`, divides integer paise by `100.0` to yield Rupees, and calls `price_cache.set_price(token, ltp)`.

---

### `app/streaming/mock_streamer.py`

#### Class `MockMarketStreamer(IMarketDataStreamer)`
- **Simulation Engine**: Generates continuous realistic random-walk price fluctuations ($\pm 0.4\%$) for Indian equity tokens (`3045`, `2885`, `11536`, `1594`, `3456`) every 2 seconds, updating `price_cache`.

---

## 7. API Endpoints & Routing Layer (`app/api/`)

### Router Aggregator (`app/api/router.py`)
- Assembles all endpoint routers into `api_router`:
  - `prices.router` (`/api/prices`)
  - `trades.router` (`/api/trades`)
  - `strategies.router` (`/api/strategies`)
  - `emotions.router` (`/api/emotions`)
  - `journal.router` (`/api/journal`)

### Endpoint Files
- **`prices.py`**: `GET /api/prices` returns live batch prices from `price_cache`.
- **`trades.py`**: Dedicated REST CRUD for `/api/trades`. Uses `TradeCreate` and `TradeUpdate` Pydantic models.
- **`strategies.py`**: Dedicated REST CRUD for `/api/strategies` (`GET`, `POST`, `DELETE /{name}`).
- **`emotions.py`**: Dedicated REST CRUD for `/api/emotions` (`GET`, `POST`, `DELETE /{name}`).
- **`journal.py`**: Aggregated overview (`GET /api/journal`), bulk actions (`/journal/reset`, `/journal/import`), and backward-compatible query-param fallback.
