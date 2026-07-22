# System Architecture & Low-Level Design (LLD) Master Specification

This document provides a comprehensive technical architecture specification for the Stock Journal application. It details the High-Level Design (HLD), Low-Level Design (LLD), component interaction models, class inheritance structures, sequence workflows, SOLID principles implementation, and database collection schemas.

---

## 1. High-Level Architecture (HLD)

The system is designed as a **Production-Grade Layered Monolith** running inside a single container environment. It integrates real-time WebSocket market tick ingestion, asynchronous non-blocking MongoDB storage, dedicated REST API routers, and static dashboard asset hosting.

### 1.1 Master System Architecture Diagram

```mermaid
graph TD
    subgraph FastAPI Monolith Process (Container)
        A[Lifespan Event] -->|1. Async Motor Connect| B[(MongoDB Database: stock_journal)]
        A -->|2. Spawn Daemon Thread| C[Market Data Streamer Daemon]
        
        C -->|Pushes Ticks| D[Thread-Safe PriceCache]
        
        E[Master APIRouter] --> F[Prices Endpoint /api/prices]
        E --> G[Trades Endpoint /api/trades]
        E --> H[Strategies Endpoint /api/strategies]
        E --> I[Emotions Endpoint /api/emotions]
        E --> J[Journal Endpoint /api/journal]
        
        F -->|Batch Read| D
        G -->|Delegates| K[ITradeRepository Interface]
        H -->|Delegates| L[IStrategyRepository Interface]
        I -->|Delegates| M[IEmotionRepository Interface]
        J -->|Delegates| N[JournalService Orchestrator]
        
        K ..|> O[MongoTradeRepository]
        L ..|> P[MongoStrategyRepository]
        M ..|> Q[MongoEmotionRepository]
        
        O -->|Async Motor Queries| B
        P -->|Async Motor Queries| B
        Q -->|Async Motor Queries| B
        
        R[StaticFiles Engine] -->|Serves Assets| S[Client Dashboard UI: static/]
    end

    S -->|2.5s Price Poll| F
    S -->|AJAX Fetch / REST CRUD| E
```

---

## 2. Sequence Workflows & Execution Diagrams

### 2.1 Market Tick Ingestion & Live Price Cache Workflow
```mermaid
sequenceDiagram
    autonumber
    participant Exchange as Angel One WebSocket V2 / Mock
    participant Streamer as Streamer Daemon Thread
    participant Cache as Thread-Safe PriceCache
    participant Client as Frontend Dashboard UI
    participant API as FastAPI GET /api/prices

    Exchange->>Streamer: 1. Send Raw Price Tick (Paise)
    Streamer->>Streamer: 2. Convert Paise to Rupees (ltp / 100.0)
    Streamer->>Cache: 3. set_price(token, ltp) [Acquires Lock]
    Cache-->>Streamer: 4. Lock Released
    loop Every 2.5 Seconds
        Client->>API: 5. GET /api/prices?tokens=3045,2885
        API->>Cache: 6. get_batch_prices(["3045", "2885"]) [Acquires Lock]
        Cache-->>API: 7. Return Price Dictionary
        API-->>Client: 8. JSON Response {"data": {...}, "timestamp": 1774...}
        Client->>Client: 9. Flash Price Tickers & Re-evaluate Position Unrealized P&L
    end
```

### 2.2 Trade Creation & Data Validation Workflow
```mermaid
sequenceDiagram
    autonumber
    participant UI as Frontend User Interface
    participant Endpoint as POST /api/trades
    participant Schema as Pydantic TradeCreate Model
    participant Repo as ITradeRepository (MongoTradeRepository)
    participant Mongo as MongoDB Collection ('trades')

    UI->>Endpoint: 1. Submit Trade Payload (Symbol, Side, Price, Shares, Notes...)
    Endpoint->>Schema: 2. Validate Data Types & Constraints (gt=0)
    alt Validation Failure
        Schema-->>UI: 422 Unprocessable Entity + Field Error List
    else Validation Success
        Endpoint->>Repo: 3. create_trade(trade_dict)
        Repo->>Mongo: 4. insert_one(doc)
        Mongo-->>Repo: 5. Return Inserted ObjectId
        Repo-->>Endpoint: 6. Formatted TradeResponse object
        Endpoint-->>UI: 7. 200 OK + JSON Trade Payload
        UI->>UI: 8. Append to Local State & Re-render Dashboard Charts
    end
```

### 2.3 Strategy Deletion & Cascading Reassignment Workflow
```mermaid
sequenceDiagram
    autonumber
    participant UI as Frontend Strategy Manager
    participant Endpoint as DELETE /api/strategies/{name}
    participant Repo as IStrategyRepository (MongoStrategyRepository)
    participant StratsColl as MongoDB Collection ('strategies')
    participant TradesColl as MongoDB Collection ('trades')

    UI->>Endpoint: 1. Request Delete Strategy ("Breakout")
    Endpoint->>Repo: 2. delete_strategy("Breakout")
    Repo->>StratsColl: 3. find_one({"name": "Breakout"})
    StratsColl-->>Repo: 4. Found Strategy Document
    Repo->>StratsColl: 5. delete_one({"_id": doc_id})
    Repo->>TradesColl: 6. update_many({"strategy": "Breakout"}, {"$set": {"strategy": "Uncategorized"}})
    TradesColl-->>Repo: 7. Modified Count (e.g. 5 trades updated)
    Repo-->>Endpoint: 8. True
    Endpoint-->>UI: 9. 200 OK {"success": true, "message": "Deleted"}
```

---

## 3. Class & Inheritance Architecture

### 3.1 Persistence Layer Class Diagram
```mermaid
classDiagram
    class ITradeRepository {
        <<interface>>
        +get_all_trades() List[dict]*
        +get_trade_by_id(trade_id: str) Optional[dict]*
        +create_trade(trade: dict) dict*
        +update_trade(trade_id: str, trade_update: dict) Optional[dict]*
        +delete_trade(trade_id: str) bool*
        +reset_trades(trades: List[dict]) None*
    }

    class IStrategyRepository {
        <<interface>>
        +get_all_strategies() List[str]*
        +add_strategy(name: str) bool*
        +delete_strategy(name: str) bool*
        +reset_strategies(strategies: List[str]) None*
    }

    class IEmotionRepository {
        <<interface>>
        +get_all_emotions() List[str]*
        +add_emotion(name: str) bool*
        +delete_emotion(name: str) bool*
        +reset_emotions(emotions: List[str]) None*
    }

    class MongoTradeRepository {
        -collection: AsyncIOMotorCollection
        +get_all_trades() List[dict]
        +get_trade_by_id(trade_id: str) Optional[dict]
        +create_trade(trade: dict) dict
        +update_trade(trade_id: str, trade_update: dict) Optional[dict]
        +delete_trade(trade_id: str) bool
        +reset_trades(trades: List[dict]) None
    }

    class MongoStrategyRepository {
        -collection: AsyncIOMotorCollection
        -trades_collection: AsyncIOMotorCollection
        +get_all_strategies() List[str]
        +add_strategy(name: str) bool
        +delete_strategy(name: str) bool
        +reset_strategies(strategies: List[str]) None
    }

    class MongoEmotionRepository {
        -collection: AsyncIOMotorCollection
        -trades_collection: AsyncIOMotorCollection
        +get_all_emotions() List[str]
        +add_emotion(name: str) bool
        +delete_emotion(name: str) bool
        +reset_emotions(emotions: List[str]) None
    }

    ITradeRepository <|.. MongoTradeRepository
    IStrategyRepository <|.. MongoStrategyRepository
    IEmotionRepository <|.. MongoEmotionRepository
```

### 3.2 Market Streaming Class Diagram
```mermaid
classDiagram
    class IMarketDataStreamer {
        <<interface>>
        +authenticate() bool*
        +connect_and_stream(tokens: list[str]) None*
        +on_tick_received(token: str, ltp: float) None*
    }

    class AngelOneSmartApiStreamer {
        -api_key: str
        -client_code: str
        -password: str
        -totp_secret: str
        -sws: SmartWebSocketV2
        +authenticate() bool
        +connect_and_stream(tokens: list[str]) None
        +on_tick_received(token: str, ltp: float) None
    }

    class MockMarketStreamer {
        -running: bool
        -prices: dict
        +authenticate() bool
        +connect_and_stream(tokens: list[str]) None
        +on_tick_received(token: str, ltp: float) None
    }

    IMarketDataStreamer <|.. AngelOneSmartApiStreamer
    IMarketDataStreamer <|.. MockMarketStreamer
```

---

## 4. SOLID Principles Mapping & Architectural Proofs

### Single Responsibility Principle (SRP)
- **Proof**: `app/core/database.py` manages **only** MongoDB connection initialization and closure. It contains zero SQL/BSON queries or routing logic. `app/streaming/price_cache.py` manages **only** thread-safe in-memory price storage.

### Open/Closed Principle (OCP)
- **Proof**: `IMarketDataStreamer` defines the streaming abstraction. Adding support for a new market data provider (e.g. `ZerodhaStreamer` or `InteractiveBrokersStreamer`) requires adding a new class implementing `IMarketDataStreamer` — **zero** changes to `price_cache.py` or `/api/prices` endpoints!

### Liskov Substitution Principle (LSP)
- **Proof**: Both `AngelOneSmartApiStreamer` and `MockMarketStreamer` can be substituted into the background daemon thread transparently without the caller caring which implementation is running.

### Interface Segregation Principle (ISP)
- **Proof**: Instead of creating a bloated `IGenericJournalRepository` with 30 methods, data access is divided into concise contracts: `ITradeRepository`, `IStrategyRepository`, and `IEmotionRepository`.

### Dependency Inversion Principle (DIP)
- **Proof**: `JournalService` in `app/services/journal_service.py` accepts `trade_repo: ITradeRepository`, `strategy_repo: IStrategyRepository`, and `emotion_repo: IEmotionRepository` in its constructor. It never imports `MongoTradeRepository` directly! FastAPI injects dependencies using `Depends()`.

---

## 5. MongoDB Database Schemas

### Database: `stock_journal`

#### Collection 1: `trades`
```json
{
  "_id": ObjectId("669ea102f..."),
  "custom_id": "trade_1",
  "symbol": "AAPL",
  "side": "BUY",
  "price": 182.50,
  "stopLoss": 178.00,
  "shares": 50,
  "pfMatrix": 1.5,
  "rsMatrix": 1.2,
  "xPercentage": 5.0,
  "strategy": "Breakout",
  "emotion": "Disciplined",
  "mistakes": ["None"],
  "notes": "AAPL breakout above $182 resistance level.",
  "date": "2026-07-01T14:30:00Z"
}
```

#### Collection 2: `strategies`
```json
{
  "_id": ObjectId("669ea109a..."),
  "name": "Breakout"
}
```

#### Collection 3: `emotions`
```json
{
  "_id": ObjectId("669ea110c..."),
  "name": "Disciplined"
}
```

---

## 6. Security, Environment Resolution & Deployment Topology

### 6.1 CORS Security Policy (`ALLOWED_ORIGINS`)
FastAPI mounts `CORSMiddleware` configured dynamically via `Settings.get_allowed_origins()` in `app/core/config.py`.
- **Development**: Accepts wildcard `*` or `http://localhost:8000`.
- **Production**: Accepts comma-separated domain whitelists defined via the `ALLOWED_ORIGINS` environment variable (e.g. `https://your-app.vercel.app,http://localhost:8000`).

### 6.2 Frontend Dynamic API Resolution (`FASTAPI_BACKEND_URL`)
Frontend assets (`static/state.js`, `static/mockApi.js`, `static/index.html`) dynamically resolve the target backend endpoint using the following fallback chain:
1. `window.FASTAPI_BACKEND_URL` (injected via Vercel Environment Variables or script configuration).
2. `window.API_BASE_URL` (legacy fallback).
3. Relative URL `""` (used when the frontend is served directly by FastAPI on Render).

### 6.3 Vercel Schema Compliance (`vercel.json`)
The Vercel deployment configuration enforces strict compliance with Vercel v2 schema rules:
```json
{
  "cleanUrls": true,
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/static/$1"
    }
  ]
}
```

