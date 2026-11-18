# System Architecture & Low-Level Design (LLD) Master Specification

This document provides a comprehensive technical architecture specification for the Stock Journal application. It details the High-Level Design (HLD), Low-Level Design (LLD), component interaction models, class inheritance structures, sequence workflows, SOLID principles implementation, and database collection schemas.

---

## 1. High-Level Architecture (HLD)

The system is designed as a **Production-Grade Layered Monolith** running inside a single container environment. It integrates real-time WebSocket market tick ingestion, asynchronous non-blocking Postgres storage, dedicated REST API routers, and static dashboard asset hosting.

### 1.1 Master System Architecture Diagram

```mermaid
graph TD
    subgraph Browser["Browser Dashboard"]
        S["Client Dashboard UI (static/)"]
    end

    subgraph Monolith["FastAPI Monolith Process (Container)"]
        A["Lifespan Event"] -->|"1. Open asyncpg Pool"| B[("Supabase Postgres: trades, strategies, emotions, watchlists")]
        A -->|"2. Spawn Daemon Thread"| C["Market Data Streamer Daemon"]
        A -->|"3. Create schema and enable RLS"| B

        C -->|"Pushes Ticks"| D["Thread-Safe PriceCache"]

        Z["get_current_user JWT Guard"] -->|"Gates every /api route"| E
        E["Master APIRouter"] --> F["Prices Endpoint /api/prices"]
        E --> G["Trades Endpoint /api/trades"]
        E --> H["Strategies Endpoint /api/strategies"]
        E --> I["Emotions Endpoint /api/emotions"]
        E --> J["Journal Endpoint /api/journal"]
        E --> W["Watchlist Endpoint /api/watchlist"]

        W -->|"Publishes owner keys"| Y["SubscriptionRegistry"]
        Y -->|"Diff applied every 15 s"| C

        F -->|"Batch Read"| D
        G -->|"Delegates"| K["ITradeRepository Interface"]
        H -->|"Delegates"| L["IStrategyRepository Interface"]
        I -->|"Delegates"| M["IEmotionRepository Interface"]
        J -->|"Delegates"| N["JournalService Orchestrator"]

        K -.->|"implements"| O["PostgresTradeRepository"]
        L -.->|"implements"| P["PostgresStrategyRepository"]
        M -.->|"implements"| Q["PostgresEmotionRepository"]

        O -->|"parameterized SQL via asyncpg"| B
        P -->|"parameterized SQL via asyncpg"| B
        Q -->|"parameterized SQL via asyncpg"| B

        %% Invisible link: keeps StaticFiles inside the process frame while its
        %% only visible edge points out to the browser.
        E ~~~ R
        R["StaticFiles Engine"] -->|"Serves Assets"| S
    end

    F -.->|"3. JSON prices, polled every 2.5s"| S
    E -.->|"4. REST JSON responses"| S
    S -.->|"5. Bearer session JWT on every call"| Z
```

### 1.2 Identity & Tenancy Pipeline (v1.5)

Supabase owns credentials and session issuance; this process owns none of it. The browser signs in with email and password through supabase-js, sends the short-lived access token as `Authorization: Bearer …`, and the API verifies it statelessly against the project's cached JWKS (or the legacy shared secret). The `sub` claim becomes the tenancy key that every repository filters on.

```mermaid
graph LR
    U["Browser"] -->|"1. Email and password"| CL["Supabase Auth"]
    CL -->|"2. Access token"| U
    U -->|"3. Bearer token"| G["get_current_user"]
    G -->|"4. Fetch JWKS once"| JW["Supabase JWKS endpoint"]
    G -->|"5. UserContext sub + email"| F["Repository factories"]
    F -->|"6. owner_id = sub"| R["Postgres repositories"]
    R -->|"7. Filtered reads and writes"| DB[("Supabase Postgres")]
    G -.->|"Dev only: AUTH_DISABLED"| DEV["Fixed dev-local subject"]
    DEV -.-> F
```

- **Fail-closed:** no `SUPABASE_URL` → every `/api/*` call gets `401`; `AUTH_DISABLED=true` in `ENV=production` → startup `RuntimeError` (and a `500` if it somehow reaches the dependency).
- **Algorithm pinning:** the accepted algorithm list is derived from the configured key (JWKS for ES256/RS256, the shared secret for HS256), never from the token header alone, so an HS256 token cannot be validated with a public JWKS key.
- **Foreign ids:** queries are owner-scoped, so another account's row simply does not match → `404`, never `403`.

---

## 2. Sequence Workflows & Execution Diagrams

### 2.1 Market Tick Ingestion & Live Price Cache Workflow
```mermaid
sequenceDiagram
    autonumber
    participant Exchange as Upstox Feed v3 / Mock
    participant Streamer as Streamer Daemon Thread
    participant Cache as Thread-Safe PriceCache
    participant Client as Frontend Dashboard UI
    participant API as FastAPI GET /api/prices

    Exchange->>Streamer: 1. Decoded live_feed Message
    Streamer->>Streamer: 2. Extract LTP from feeds[instrument_key].ltpc
    Streamer->>Cache: 3. set_price(instrument_key, ltp) acquires lock
    Cache-->>Streamer: 4. Lock Released
    loop Every 2.5 Seconds
        Client->>API: 5. GET /api/prices?tokens=instrument_keys
        API->>Cache: 6. get_batch_prices(tokens) acquires lock
        Cache-->>API: 7. Return LTP dictionary
        API-->>Client: 8. JSON with data, meta and timestamp
        Client->>Client: 9. Flash Price Tickers and Re-evaluate Unrealized P&L
    end
```

### 2.2 Trade Creation & Data Validation Workflow
```mermaid
sequenceDiagram
    autonumber
    participant UI as Frontend User Interface
    participant Endpoint as POST /api/trades
    participant Schema as Pydantic TradeCreate Model
    participant Repo as ITradeRepository (PostgresTradeRepository)
    participant TradesTable as trades table

    UI->>Endpoint: 1. Submit Trade Payload (Symbol, Side, Price, Shares, Notes...)
    Endpoint->>Schema: 2. Validate Data Types & Constraints (gt=0)
    alt Validation Failure
        Schema-->>UI: 422 Unprocessable Entity + Field Error List
    else Validation Success
        Endpoint->>Repo: 3. create_trade(trade_dict)
        Repo->>TradesTable: 4. INSERT (owner_id, id, data jsonb)
        TradesTable-->>Repo: 5. Return the stored id
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
    participant Repo as IStrategyRepository (PostgresStrategyRepository)
    participant StratsColl as strategies table
    participant TradesColl as trades table

    UI->>Endpoint: 1. Request Delete Strategy ("Breakout")
    Endpoint->>Repo: 2. delete_strategy("Breakout")
    Repo->>StratsColl: 3. BEGIN; DELETE ... WHERE lower(name) = lower($2) RETURNING name
    StratsColl-->>Repo: 4. Deleted row (stored casing), or no row
    Repo->>TradesColl: 5. UPDATE trades SET data = data || jsonb_build_object(strategy, Uncategorized)
    TradesColl-->>Repo: 6. Rows updated (e.g. 5 trades)
    Repo->>StratsColl: 7. COMMIT
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

    class PostgresTradeRepository {
        -pool: asyncpg.Pool
        -owner_id: str
        +get_all_trades() List[dict]
        +get_trade_by_id(trade_id: str) Optional[dict]
        +create_trade(trade: dict) dict
        +update_trade(trade_id: str, trade_update: dict) Optional[dict]
        +delete_trade(trade_id: str) bool
        +reset_trades(trades: List[dict]) None
    }

    class PostgresStrategyRepository {
        -store: TagStore
        +get_all_strategies() List[str]
        +add_strategy(name: str) bool
        +delete_strategy(name: str) bool
        +reset_strategies(strategies: List[str]) None
    }

    class PostgresEmotionRepository {
        -store: TagStore
        +get_all_emotions() List[str]
        +add_emotion(name: str) bool
        +delete_emotion(name: str) bool
        +reset_emotions(emotions: List[str]) None
    }

    ITradeRepository <|.. PostgresTradeRepository
    IStrategyRepository <|.. PostgresStrategyRepository
    IEmotionRepository <|.. PostgresEmotionRepository
    PostgresStrategyRepository *-- TagStore
    PostgresEmotionRepository *-- TagStore
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

    class UpstoxMarketStreamer {
        -access_token: str
        -streamer: MarketDataStreamerV3
        +authenticate() bool
        +connect_and_stream(tokens: list[str]) None
        +on_tick_received(token: str, ltp: float) None
        +_extract_ltp(feed: dict)$ float
    }

    class MockMarketStreamer {
        -running: bool
        -prices: dict
        +authenticate() bool
        +connect_and_stream(tokens: list[str]) None
        +on_tick_received(token: str, ltp: float) None
    }

    IMarketDataStreamer <|.. UpstoxMarketStreamer
    IMarketDataStreamer <|.. MockMarketStreamer
```

---

## 4. SOLID Principles Mapping & Architectural Proofs

### Single Responsibility Principle (SRP)
- **Proof**: `app/core/database.py` manages **only** Postgres pool lifecycle and the `jsonb` codec. It contains zero SQL statements or routing logic (the DDL lives in `app/core/schema.py`, and every query lives in a repository). `app/streaming/price_cache.py` manages **only** thread-safe in-memory price storage.

### Open/Closed Principle (OCP)
- **Proof**: `IMarketDataStreamer` defines the streaming abstraction. Adding support for a new market data provider (e.g. `ZerodhaStreamer` or `InteractiveBrokersStreamer`) requires adding a new class implementing `IMarketDataStreamer` — **zero** changes to `price_cache.py` or `/api/prices` endpoints!

### Liskov Substitution Principle (LSP)
- **Proof**: Both `UpstoxMarketStreamer` and `MockMarketStreamer` can be substituted into the background daemon thread transparently without the caller caring which implementation is running.

### Interface Segregation Principle (ISP)
- **Proof**: Instead of creating a bloated `IGenericJournalRepository` with 30 methods, data access is divided into concise contracts: `ITradeRepository`, `IStrategyRepository`, and `IEmotionRepository`.

### Dependency Inversion Principle (DIP)
- **Proof**: `JournalService` in `app/services/journal_service.py` accepts `trade_repo: ITradeRepository`, `strategy_repo: IStrategyRepository`, and `emotion_repo: IEmotionRepository` in its constructor. It never imports `PostgresTradeRepository` directly! FastAPI injects dependencies using `Depends()`.

---

## 5. Postgres Schema (Supabase)

Created idempotently by `app/core/schema.py` on boot, under a `pg_advisory_xact_lock` so two instances cannot race. Every table carries `owner_id`; Row Level Security is **enabled on all four tables with no policies**, which denies Supabase's PostgREST (anon key) while leaving the owning role — the backend's connection — unaffected.

```sql
CREATE TABLE trades (
    owner_id text NOT NULL,
    id       text NOT NULL,
    seq      bigint GENERATED ALWAYS AS IDENTITY,
    data     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX trades_owner_seq ON trades (owner_id, seq);

CREATE TABLE strategies (owner_id text NOT NULL, name text NOT NULL CHECK (btrim(name) <> ''),
                          seq bigint GENERATED ALWAYS AS IDENTITY);
CREATE UNIQUE INDEX strategies_owner_name ON strategies (owner_id, lower(name));
-- emotions is identical, with emotions_owner_name

CREATE TABLE watchlists (owner_id text PRIMARY KEY, keys text[] NOT NULL DEFAULT '{}',
                         updated_at timestamptz NOT NULL DEFAULT now());
```

#### Row shape: `trades`

Trade fields live in one `jsonb` document so an import keeps its exact shape (GAP-2 is still open) and an explicit `null` clears a field (`data = data || patch`). Identity is owned by the columns, never by the document:

```json
{
  "owner_id": "8f14e45f-ceea-467f-a8d3-...",
  "id": "trade_1",
  "seq": 1,
  "data": {
    "symbol": "AAPL", "side": "BUY", "price": 182.50, "stopLoss": 178.00,
    "shares": 50, "pfMatrix": 1.5, "rsMatrix": 1.2, "xPercentage": 5.0,
    "strategy": "Breakout", "emotion": "Disciplined", "mistakes": ["None"],
    "notes": "AAPL breakout above $182 resistance level.", "date": "2026-07-01T14:30:00Z"
  }
}
```

- `id` is the public trade id (`trade_1` survives an import); a create without one gets a uuid4 hex, and a clash gets a fresh id instead of overwriting.
- `seq` gives the read order (`ORDER BY seq`), mirroring insertion order.

#### Row shape: `strategies` / `emotions`

One row per tag: `(owner_id, name, seq)`. The unique index on `(owner_id, lower(name))` is what makes a duplicate a `400` rather than a race, and inserts use `ON CONFLICT DO NOTHING`.

#### Row shape: `watchlists`

`(owner_id, keys text[], updated_at)`, upserted with `ON CONFLICT (owner_id) DO UPDATE`; a missing row means "use the shared `TOKENS` default".

### 5.1 Persistence Contracts (SPEC-PER-5)

An update carries only the keys present in the request body (`exclude_unset`): an **absent** key never reaches SQL, an explicit `null` is written as a JSON null (`data || patch` merges the document), and an empty body returns the current row unchanged. `reset_*` deletes and re-inserts inside one transaction, so a concurrent reader sees the old journal or the new one, never an empty one.

---

## 6. Security, Environment Resolution & Deployment Topology

### 6.1 CORS Security Policy (`ALLOWED_ORIGINS`)
FastAPI mounts `CORSMiddleware` configured dynamically via `Settings.get_allowed_origins()` in `app/core/config.py`, with `allow_credentials=False` (bearer tokens travel in the `Authorization` header, and a wildcard origin cannot be combined with credentials anyway).
- **Development**: Accepts wildcard `*` or `http://localhost:8000`.
- **Production**: Accepts comma-separated domain whitelists defined via the `ALLOWED_ORIGINS` environment variable (e.g. `https://your-app.vercel.app,http://localhost:8000`).

CORS is **not** the authorization boundary: identity is enforced per request by `get_current_user` (see 1.2), so an origin that slips through the allowlist still needs a valid Supabase session for another account's data.

### 6.2 Frontend Dynamic API Resolution (`FASTAPI_BACKEND_URL`)
`static/api.js` is the single place that resolves the backend host and attaches the session token:
1. `window.FASTAPI_BACKEND_URL` (set in `static/index.html`; empty means same origin).
2. Relative URL `""` (used on Render and behind the Vercel rewrite).
3. `Authorization: Bearer <Supabase access token>` is added on every call; a `401` signs the user out and returns to the sign-in gate.

`static/auth.js` resolves its Supabase URL and anon key from `GET /auth/config`, so no key is baked into the HTML.

### 6.3 Vercel Schema Compliance (`vercel.json`)
The Vercel deployment configuration enforces strict compliance with Vercel v2 schema rules:
```json
{
  "cleanUrls": true,
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://stock-journal-xenm.onrender.com/api/:path*" },
    { "source": "/auth/config", "destination": "https://stock-journal-xenm.onrender.com/auth/config" },
    { "source": "/(.*)", "destination": "/static/$1" }
  ]
}
```

### 6.4 Authentication Environment Matrix

| Variable | Local dev | Render production |
| --- | --- | --- |
| `ENV` | `development` (default) | `production` |
| `SUPABASE_URL` | optional (dev bypass) | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | optional | the project's anon public key |
| `SUPABASE_JWT_SECRET` | unset | only for legacy HS256 projects |
| `DATABASE_URL` | local Postgres or omitted | Supabase **session pooler** URI |
| `AUTH_DISABLED` | `true` for a Supabase-free loop | `false` (a `true` here aborts startup) |
| `DEV_USER_ID` | `dev-local` (default) | unused |
| `ALLOWED_ORIGINS` | `*` | the exact Vercel origin |

`GET /health` reports `auth` (`supabase` or `dev-bypass`), `database` (`ok` or `unavailable`) and the streamer state, so a misconfiguration is visible without reading logs.

