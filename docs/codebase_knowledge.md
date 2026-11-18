# Codebase Knowledge Base

A module-oriented knowledge map of `stock-journal`, distilled from the code itself (not from intent docs).
Use it as the entry point before changing code; use the documents in [§9](#9-related-documents) for narrative depth.

**Fastest orientation:** `main.py` → `app/api/endpoints/*` (guarded by `app/core/security.py`) → `app/services/journal_service.py` → `app/repositories/{interfaces,postgres,memory}` → `static/api.js` → `static/state.js` → `static/app.js`.

---

## 1. System Snapshot

| Dimension | Fact |
| --- | --- |
| What it is | Multi-user trading journal + portfolio dashboard: log trades with strategy / mindset tags, see P&L, equity curve, and per-strategy / per-emotion performance |
| Shape | Single FastAPI process that (a) serves a REST API under `/api`, (b) serves the static SPA from `/`, (c) runs a market-data streamer on a daemon thread |
| Identity | Supabase Auth (email + password, configured on the Supabase side). The SPA signs in through supabase-js and sends `Authorization: Bearer <access token>`; the API verifies it statelessly against the project JWKS (or the legacy HS256 secret) |
| Tenancy | Every row carries `owner_id` (= Supabase `sub`, a UUID). Repositories are constructed per request with that owner and filter every read/write; foreign ids answer `404` |
| Persistence | Supabase Postgres via `asyncpg` (pooler URI in `DATABASE_URL`), tables `trades`, `strategies`, `emotions`, `watchlists`; the schema is created idempotently at startup |
| Live prices | Broker WebSocket (Upstox market data feed v3) or synthetic mock streamer → in-process `price_cache` → browser polls `GET /api/prices` every 2.5 s. One socket serves every account; a registry diffs the union of watchlists |
| Abuse limits | In-memory sliding-window rate limit on mutations per `(user, ip)` + hard per-user caps checked before insert |
| Frontend | Vanilla ES modules, no build step, Chart.js from CDN. All analytics are computed **client-side**; responsive down to ~360px wide |
| Deployment | Backend/streamer on Render; static UI on Vercel with `/api/*` and `/auth/config` rewritten to the Render host (`vercel.json`) |
| Tests | pytest (+ pytest-asyncio, TestClient, in-memory repositories, real Postgres via `pgserver`), 78 tests |

Two independent state owners exist by design: the server (Postgres, authoritative) and the browser (`state.js`, optimistic + localStorage fallback). Most surprises in this repo come from that split.

---

## 2. Module Cards

### M0 — Entrypoint & Lifecycle · `main.py`
- **Role:** builds the app, wires middleware, starts/stops infrastructure.
- **Key symbols:** `app`, `lifespan()`, `start_streamer_daemon()`, `run()` (daemon loop), `sync_subscriptions()`.
- **Sequence:** `lifespan` → `validate_auth_config()` (raises only for `AUTH_DISABLED` + `ENV=production`) → `await connect_to_database()` (opens the asyncpg pool, then `ensure_schema()`) → `start_streamer_daemon()` (thread, `daemon=True`) → serve → `await close_database_connection()`.
- **Streamer selection:** mock if `MOCK_STREAMER=true` **or** `UPSTOX_ACCESS_TOKEN` is missing; otherwise `UpstoxMarketStreamer`. Each attempt runs one streamer plus a subscription-sync thread; failures retry after a 10 s sleep.
- **Supervision:** the loop marks `mode`/`connected` via `app/streaming/status.py`, applies `diff_subscriptions()` deltas every `STREAMER_SYNC_SECONDS`, and reconnects once the transport has been connected and then reports closed (the `was_connected` latch exists because Upstox's `connect()` returns immediately).
- **Routing order:** `app.include_router(health.router)` (public) → `app.include_router(auth_config.router)` (public, `GET /auth/config`) → `app.include_router(api_router)` (authenticated) → `app.mount("/", StaticFiles(directory="static", html=True))`. The public routers must stay registered *before* the mount or they are swallowed by the static files.
- **Run:** `python main.py` → uvicorn `0.0.0.0:$PORT` (default `8000`), importing `"main:app"` as a string.
- **Gotcha:** the streamer is a *blocking* sync loop inside one process. Scaling past one instance duplicates the subscription; serverless hosts cannot run it.

### M1 — Configuration · `app/core/config.py`
- **Role:** plain `Settings` class (not `pydantic-settings`) reading `.env` via `python-dotenv`, exposed as a module-level singleton `settings`.
- **Environment variables:** `UPSTOX_ACCESS_TOKEN`, `MOCK_STREAMER`, `TOKENS` (default 5 NSE instrument keys `"NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022"` = SBIN, PNB, TCS, INFY, WIPRO), `PRICE_MAX_AGE_SECONDS`, `ALLOWED_ORIGINS` (default `*`), `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` (falls back to `SUPABASE_PUBLISHABLE_KEY`), `SUPABASE_JWT_SECRET`, `ENV`, `AUTH_DISABLED`, `DEV_USER_ID`, `MUTATION_RATE_LIMIT_PER_MINUTE`, `MAX_TRADES_PER_USER`, `MAX_STRATEGIES_PER_USER`, `MAX_EMOTIONS_PER_USER`, `MAX_WATCHLIST_KEYS` (legacy alias `WATCHLIST_MAX_KEYS`), `WATCHLIST_TTL_SECONDS`, `STREAMER_SYNC_SECONDS`.
- **Helpers:** `get_allowed_origins()`, `get_tokens()` (CSV → list, blank-tolerant), `has_upstox_credentials()` (token present), `is_production()`, `supabase_issuer()` (`f"{SUPABASE_URL}/auth/v1"`, the exact `iss` claim), `auth_mode()` (`supabase` / `dev-bypass`), `validate_auth_config()` (startup guard; a missing `SUPABASE_URL` or `SUPABASE_ANON_KEY` only logs, so the API fails closed with `401`s instead of opening itself).
- **Convention:** new config = new `os.getenv` attribute + (if list/CORS-like) a parsing helper. Never read `os.getenv` outside this module.

### M2 — Database Handle · `app/core/database.py`
- **Role:** single asyncpg pool holder + FastAPI dependency; the DDL lives next door in `schema.py`.
- **Key symbols:** `create_pool(dsn)`, `ssl_mode_for(dsn)`, `dsn_problems(dsn)`, `connect_to_database()`, `close_database_connection()`, `get_pool()`, `database_status()`.
- **Behaviour:** `min_size=1`, `max_size=5`, `command_timeout=30`, and **`statement_cache_size=0`** because Supabase's pooler cannot keep server-side prepared statements. `ssl` is `require` for any non-loopback host whose DSN does not say otherwise, since `asyncpg` reads a bare DSN as `disable`. Every connection gets a `jsonb` codec, so repositories pass plain dicts. `connect_to_database()` runs `dsn_problems()` first - a reserved character in the password (`?`, `#`) truncates the URI and `asyncpg` blames a bogus query field - then `ensure_schema()`.
- **Failure mode:** a pool that cannot open (bad DSN, IPv6-only direct host, wrong password) is logged, not raised - the app still boots, `/health` reports `database: unavailable`, and data routes answer `503` from `get_pool()` instead of per-request `500`s.
- **Extension point:** repository factories take `pool: asyncpg.Pool = Depends(get_pool)` - tests override the *endpoint* factories, not this one.

### M2b — Identity, Abuse Guards & Schema · `app/core/{security,limits,schema}.py`
| File | Role |
| --- | --- |
| `security.py` | `UserContext` (frozen dataclass: `user_id`, `email`, `authenticated`) + `get_current_user` dependency + `verify_session_token`. Bearer token → algorithm read from the header, then **only that family** is trusted: `HS256` against `SUPABASE_JWT_SECRET`, `RS256`/`ES256` against `jwt.PyJWKClient(<SUPABASE_URL>/auth/v1/.well-known/jwks.json, cache_keys=True, lifespan=3600)`. `jwt.decode(..., audience="authenticated", options={"require": ["exp","iss","sub","aud"]})`. The client and its lock are lazy module-level singletons. Every failure maps to `401` with a generic detail (no leak of *why*). With `AUTH_DISABLED=true` it returns `UserContext(settings.DEV_USER_ID, "dev@localhost", authenticated=False)` - but raises `500` if `ENV=production` |
| `limits.py` | `mutation_rate_limit` dependency (60 s sliding window per `"{user_id}:{ip}"`, `429` + `Retry-After: 60`, disabled when `MUTATION_RATE_LIMIT_PER_MINUTE <= 0`), `enforce_cap(current, cap, label)` → `400`, and `reset_rate_limit_buckets()` for tests. Process-local by design |
| `schema.py` | `SCHEMA_SQL` + `ensure_schema(pool)`: one idempotent script (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`) run inside a transaction holding `pg_advisory_xact_lock(...)`, so two instances booting together cannot race. RLS is enabled with **no policies**, which denies anon/PostgREST access while the backend role bypasses it |

- **Why the constructors, not the interfaces:** `Postgres*Repository(pool, owner_id)` keeps the three ABCs unchanged (the store-swap seam) and lets FastAPI build a fresh owner-scoped repository per request from `get_current_user`.

### M3 — API Router · `app/api/router.py`
- **Role:** one `APIRouter` (`api_router`) with all six endpoint modules mounted under prefix `/api` and tags `Prices`, `Trades`, `Strategies`, `Emotions`, `Watchlist`, `Journal Overview & Maintenance`.
- **Note:** prefixes are declared here, not in the endpoint modules - endpoint files create a bare `APIRouter(dependencies=[Depends(get_current_user)])`. `GET /health` and `GET /auth/config` are **not** part of this router: they are public and included separately in `main.py` before the static mount.

### M4 — Endpoint Modules · `app/api/endpoints/`
Each module owns its own dependency factory that *instantiates* a repository from the pool.

| File | Routes | Dependency factory | Backing store |
| --- | --- | --- | --- |
| `health.py` | `GET /health` (public, separate router) | none | `status` snapshot + `price_cache` + `database_status()` |
| `auth_config.py` | `GET /auth/config` (public, separate router) | none | `settings` (`provider`, `url`, `anonKey`, or `provider: "none"`) |
| `prices.py` | `GET /api/prices?tokens=a,b` | none (imports the `price_cache` singleton) | in-process cache |
| `trades.py` | `GET /api/trades`, `GET/PUT/DELETE /api/trades/{trade_id}`, `POST /api/trades` | `get_trade_repo` → `PostgresTradeRepository(pool, user.user_id)` | Postgres |
| `strategies.py` | `GET/POST /api/strategies`, `DELETE /api/strategies/{name}` | `get_strategy_repo` → `PostgresStrategyRepository` | Postgres |
| `emotions.py` | `GET/POST /api/emotions`, `DELETE /api/emotions/{name}` | `get_emotion_repo` → `PostgresEmotionRepository` | Postgres |
| `watchlist.py` | `GET/PUT /api/watchlist` | `get_watchlist_repo` → `PostgresWatchlistRepository` | Postgres |
| `journal.py` | `GET /api/journal`, `POST /api/journal/reset`, `POST /api/journal/import` (legacy `?action=&type=` routes removed) | `get_journal_service` → `JournalService(Postgres*, Postgres*, Postgres*)` | Postgres |

- **Authentication:** declared once per router (`APIRouter(dependencies=[Depends(get_current_user)])`), so it cannot be forgotten on a new route. FastAPI caches the dependency, so the access token is verified once per request and the same `UserContext` feeds the repository factory.
- **Response envelope (universal):** `{"success": true, "data": ...}` for reads/writes, `{"success": true, "message": "..."}` for verbs without a payload.
- **Error idiom:** `raise HTTPException(status_code=404|400, detail="...")`. No try/except in endpoints; unexpected exceptions bubble to FastAPI's 500 handler. Foreign-owner rows answer `404` (never `403`) so ids cannot be probed. A missing pool surfaces as `503` from `get_pool()`.
- **Write guards:** `POST /trades`, `POST /strategies`, `POST /emotions` call `enforce_cap(len(await repo.get_all_*()), settings.MAX_*_PER_USER, "Trade")` first; every mutating route also carries `Depends(mutation_rate_limit)`.
- **`prices.py`:** empty/missing `tokens` → `{"data": {}, "meta": {}, "timestamp": <ms epoch>}`. Unknown tokens come back as `100.0` (cache default), never as missing keys, and are flagged `meta[token] = {as_of: null, stale: true}`. Prices are global, not per owner.
- **`journal.py` is one REST surface:** `/journal` (GET only), `/journal/reset`, `/journal/import`. The old query-param compat handlers (`POST ?action=|type=`, `PUT ?id=`, `DELETE ?type=&name=|?id=`) were removed in GAP-3b and now return 405.
- **`/journal/import`** reads a raw `await request.json()` (no Pydantic model) and calls the owner-scoped `reset_*` methods. It now refuses a payload whose `trades`/`strategies`/`emotions` are not lists, or whose trade count exceeds `MAX_TRADES_PER_USER`; individual trade dicts still skip validation and sanitisation (GAP-2).
- **`watchlist.py`:** `GET` returns the stored keys, falling back to `settings.get_tokens()` for an account that never saved one; both verbs call `subscriptions.set_user_keys(user_id, keys)` so the streamer picks the change up on its next sync.
- **Gotcha:** `DELETE /api/strategies/{name}` and `/api/emotions/{name}` take a raw path segment — callers must `encodeURIComponent` (names contain spaces, e.g. `Pullback Support`).

### M5 — Domain Service · `app/services/journal_service.py`
- **Role:** the only place with domain rules: default taxonomy, seeding, overview assembly, reset.
- **Key symbols:** `JournalService`, `DEFAULT_STRATEGIES` (Breakout, Pullback Support, Gap Fill, Trend Continuation, Mean Reversion), `DEFAULT_EMOTIONS` (Disciplined, Confident, Neutral, Anxious, FOMO, Greedy), `INITIAL_TRADES` (9 seed trades, ids `trade_1`-`trade_9`).
- **Constructor takes the three *interfaces*** (`ITradeRepository`, `IStrategyRepository`, `IEmotionRepository`) - the only genuine dependency-inversion point in the app.
- **`seed_if_empty()`** seeds each table independently, only when empty. It is called from `get_journal_overview()`, i.e. **seeding is a side effect of the first `GET /api/journal`**, not of startup.
- **`get_journal_overview()`** returns `{"trades", "strategies", "emotions"}`; everything else (`add_trade`, `update_trade`, `delete_trade`, `add_strategy`, ...) is a one-line pass-through to a repository.
- **`reset_to_mock()`** = reset all three tables to the constants above (each reset is one transaction, so a reader never sees an empty journal).
- **Extension point:** any new cross-entity rule (e.g. "block deleting a strategy that has open positions") belongs here, not in an endpoint.

### M6 — Pydantic Models · `app/models/`
| Model | Notes |
| --- | --- |
| `TradeCreate` | Required: `symbol`, `price (>0)`, `shares (>0)`. Defaulted: `side="BUY"`, `strategy="Uncategorized"`, `emotion="Neutral"`, `mistakes=["None"]`, `notes=""`, `date=now UTC ISO`. Optional: `stopLoss`, `pfMatrix`, `rsMatrix`, `xPercentage` |
| `TradeUpdate` | All fields optional; intended for `model_dump(exclude_unset=True)` partial updates |
| `TradeResponse` | Read model for every trade endpoint: same wire fields as `TradeCreate` **without** the input validators (re-sanitising would double-escape stored text) |
| `responses.py` models | `DataResponse[T]`, `MessageResponse`, `PriceMeta`, `PricesResponse`, `JournalOverview`, `JournalResponse` — wired as `response_model` on all routes (GAP-8b) |
| `StrategyCreate` / `EmotionCreate` | Single `name: str = Field(..., min_length=1)` |

- **Validators (Pydantic v2 `@field_validator` + `@classmethod`):** `symbol` → `strip().upper()`; `side` → upper + membership check in `{"BUY","SELL"}`; `notes`/`strategy`/`emotion` → `html.escape(strip())`.
- **Consequence:** stored text is HTML-escaped at the boundary, so `&` becomes `&amp;` in the `jsonb` document and the frontend escapes again on render.
- **Convention:** field names are `camelCase` on the wire (`stopLoss`, `pfMatrix`, `xPercentage`) to match the JS frontend — do not rename without touching `static/app.js` and `static/state.js`.

### M7 — Repository Contracts · `app/repositories/interfaces/`
- `ITradeRepository` (ABC): `get_all_trades`, `get_trade_by_id`, `create_trade`, `update_trade`, `delete_trade`, `reset_trades` — all `async`.
- `IStrategyRepository` / `IEmotionRepository`: `get_all_*`, `add_*`, `delete_*`, `reset_*`.
- `IWatchlistRepository`: `get_keys() -> list[str]`, `set_keys(keys) -> list[str]`.
- **Contract detail:** repository methods exchange plain `dict`s / `list[str]`, never Pydantic models, and models are imported by the interface files but unused. **Ownership is not a method parameter** - it is constructor state (`Postgres*Repository(pool, owner_id)`), which is what keeps these ABCs stable.
- **Rule of thumb:** a method missing here cannot be reached by the service; adding behaviour means changing the interface **and both live implementations** (`postgres/`, `memory/`).

### M8 — Postgres Implementations · `app/repositories/postgres/`
- **Tables:** `trades(owner_id, id, seq identity, data jsonb, PK(owner_id, id))`, `strategies`/`emotions(owner_id, name, seq)` with a unique `(owner_id, lower(name))` index, `watchlists(owner_id PK, keys text[], updated_at)`. Full DDL in `architecture.md` §5.
- **Owner scoping:** every repository takes `owner_id` in the constructor (`ValueError` when blank). Every statement carries `WHERE owner_id = $1`; inserts stamp `owner_id` from the server and strip it from the payload (`_IDENTITY_KEYS = ("id", "owner_id", "custom_id", "_id")` never reaches the jsonb document).
- **ID translation (trades):** identity is the `id` text column and `seq` (identity) preserves insert order. `_to_trade(row)` returns `{**row["data"], "id": row["id"]}` - an imported `trade_1` simply *is* the row id, so the old `custom_id` indirection is gone.
- **`create_trade`:** `INSERT ... ON CONFLICT DO NOTHING RETURNING id`; a clash (an imported id that already exists) retries once with a fresh `uuid4().hex` instead of overwriting the existing trade.
- **`update_trade`:** `data = data || $3::jsonb`. Keys absent from the payload are never in the patch (`exclude_unset` upstream), so they stay untouched; an explicit `None` writes a JSON null, i.e. clears the field. An empty patch is a read.
- **`reset_*` (all three):** one transaction - `DELETE ... WHERE owner_id = $1` then `executemany(INSERT ...)`; readers see the old set or the new one, never an empty one, and only the caller is touched. Duplicate or absent ids are replaced with fresh uuids.
- **Duplicate detection (strategies/emotions):** the unique index decides. `TagStore.add()` uses `ON CONFLICT DO NOTHING RETURNING seq`, so a duplicate - even one racing this request - is a `False`/`400`, never a `500`.
- **`TagStore`:** the two tag repositories are thin wrappers over one shared SQL object (`table` + `trade_field` + `fallback`; the table name is validated against an allowlist because it is interpolated). Delete is one transaction: `DELETE ... WHERE lower(name) = lower($2) RETURNING name` then `UPDATE trades SET data = data || jsonb_build_object($2::text, $3::text) WHERE owner_id = $1 AND data->>$2::text = $4` → `Uncategorized` / `Neutral`, matching the *stored* casing.
- **`watchlist`:** one row per owner (`INSERT ... ON CONFLICT (owner_id) DO UPDATE`), `keys` is a `text[]`.
- **Gotcha:** table/column names are the only interpolated SQL; every value is a bind parameter. A new tag table means extending `_TABLES` and the schema, not writing new SQL.

### M9 — In-Memory Implementations · `app/repositories/memory/`
- **Role:** test doubles / reference implementations of M7. List/dict-backed, fully `async`, no I/O.
- **Constructor signature mirrors Postgres:** `MemoryTradeRepository(owner_id)` / `MemoryStrategyRepository(owner_id, names=None, trade_repo=None)` / `MemoryEmotionRepository(...)` / `MemoryWatchlistRepository(owner_id)`. Stored docs are stripped of `owner_id` and filtered per owner on the way out.
- **`MemoryTradeRepository`:** optional `initial_trades`; `create_trade` mints `trade_mem_<n>` when no `id` is supplied; matches `id` or `custom_id`.
- **`MemoryStrategyRepository` / `MemoryEmotionRepository`:** optional seeded names plus an optional `trade_repo` used to perform the same cascade (loop + `update_trade`) as the SQL `TagStore`.
- **Gotcha:** the application never injects these — only the `tests/conftest.py` fixtures do, via `app.dependency_overrides`.

### M10 — Streaming Subsystem · `app/streaming/`
| File | Role |
| --- | --- |
| `base_streamer.py` | `IMarketDataStreamer` ABC: `authenticate() -> bool`, `connect_and_stream(tokens) -> None`, `on_tick_received(token, ltp) -> None` — all **synchronous** — plus `update_subscriptions(tokens) -> bool` (default `False` = "cannot re-subscribe, reconnect me") and `is_connected() -> bool` (default `True`) |
| `price_cache.py` | `PriceCache` + module singleton `price_cache`; stores `(ltp, timestamp)` per instrument key under a `threading.Lock`; `get_price`/`get_batch_prices` return the last known LTP (default `100.0` only for never-seen keys); `get_batch_meta` reports `as_of`/`stale` against `PRICE_MAX_AGE_SECONDS` (default 30); `has_fresh_data()` feeds `/health` |
| `subscriptions.py` | `diff_subscriptions(current, wanted) -> (subscribe, unsubscribe)` + `SubscriptionRegistry` (`set_defaults`, `set_user_keys`, `drop_user`, `snapshot`). `snapshot()` prunes accounts idle for `WATCHLIST_TTL_SECONDS` and returns the sorted union; module singleton `subscriptions` is written by the API and read by the daemon |
| `status.py` | `mark(...)` / `snapshot()` — the daemon's `mode` / `connected` / `changed_at` state read by `GET /health` |
| `mock_streamer.py` | Seeds the 5 default instrument keys (SBIN 650, PNB 80, TCS 3500, INFY 1500, WIPRO 450); every 2 s nudges up to 2 random keys by ±0.4 % and calls `on_tick_received`; unknown watchlist keys are seeded at `100.0`; honours `update_subscriptions` in place |
| `upstox_streamer.py` | `upstox_client.Configuration` + `access_token` → `MarketDataStreamerV3` (official `upstox-python-sdk`); subscribes `tokens` in `"ltpc"` mode on open; decoded v3 messages are `{"type": "live_feed", "feeds": {"<instrument_key>": {…}}}` and `_extract_ltp` reads `ltpc` at `feeds[key]`, `fullFeed.marketFF/.indexFF`, or `firstLevelWithGreeks`; `market_info` messages are ignored; `upstox_client` is imported lazily so mock mode works without the SDK installed; `update_subscriptions` drives the SDK's subscribe/unsubscribe helpers and returns `False` if the transport is not open |


- **Credentials:** `UPSTOX_ACCESS_TOKEN` holds the Upstox **Analytics Access Token** — read-only, one-year validity, accepted by the Market Data and Streaming APIs (no OAuth app, client id/secret or daily refresh). `authenticate()` only checks presence, and a revoked/expired token surfaces as a WebSocket error logged by `on_error` (the daemon then retries every 10 s).

- **Threading contract:** the streamer thread writes to `price_cache`; the asyncio event loop only reads it. That is why a `threading.Lock` (not an `asyncio.Lock`) is used — never `await` inside `PriceCache`.
- **Extension point:** a new provider = implement `IMarketDataStreamer` + add a branch in `start_streamer_daemon()`; `on_tick_received` is already the cache sink.
- **Gotcha:** a token that never ticks reports `100.0`; it is now distinguishable because `meta[token].stale` is `true` (same flag used for a dead feed).

### M11 — Static SPA · `static/`
| File | Role / key facts |
| --- | --- |
| `index.html` | Shell only (~636 lines): sign-in gate (`#auth-gate` > `#auth-form` with email + password, `hidden` until `auth.js` decides), 5 views (`dashboard`, `tradelog`, `strategies`, `emotions`, `analytics`), 2 modals (add/edit trade, trade detail), toast container, mistake pills, sidebar account row + watchlist add form. Sets `window.FASTAPI_BACKEND_URL` before loading modules (empty on `localhost`/`127.0.0.1`/`[::1]`, the Render host otherwise); no keys live in the HTML any more. Assets are version-tagged `?v=2.12` |
| `auth.js` | Supabase gate: reads `window.SUPABASE_URL`/`SUPABASE_ANON_KEY` if present, else `GET /auth/config`; dynamically imports `@supabase/supabase-js` from jsDelivr, `createClient({persistSession, autoRefreshToken, detectSessionInUrl:false})`, `onAuthStateChange` (reveal the app, reload once a rejected session is dropped), sign-in / sign-up toggle, `friendlyError()`, `getAuthToken()` (refreshes inside a 30 s window), `clearLocalJournalKeys()`, `handleUnauthorized()`, `signOut()`, `currentUserEmail()`, `authMode()`. A `provider: "none"` config = dev mode: the gate is skipped and no `Authorization` header is sent |
| `api.js` | `getBaseUrl()` + `apiFetch(path, options)`: awaits `authReady`, adds `Authorization: Bearer <token>`, defaults `Content-Type: application/json` for bodies, and on `401` calls `handleUnauthorized()` (sign-out) then throws. **Every** server call goes through it |
| `state.js` | `StateManager` singleton `stateManager`: `loadState()` (GET `/api/journal`, then localStorage keys `stock_journal_trades|strategies|emotions`, then `initialTrades`), CRUD with **optimistic local mutation + fire-and-forget `apiFetch`**, `exportData()/importData()` (POST `/api/journal/import`), `resetToMock()` (POST `/api/journal/reset`), `clearAll()`, and the analytics engine `getMetrics(currentPrices)` |
| `app.js` | ~1240 lines of DOM/render + event wiring: `escapeHtml`, `showToast`, `initCharts` (Chart.js: `equityChart`, `allocationChart`), `renderDashboardView/renderTradeLogView/renderStrategiesView/renderEmotionsView/renderAnalyticsView`, `renderWatchlist`/`loadWatchlist`/`saveWatchlist`/`addWatchlistKey`/`removeWatchlistKey`/`updateCustomWatchPrices`, `updateAllViews()`, modal open/close, `startMarketTickerSubscription()`, and every listener inside one `DOMContentLoaded` block |
| `mockApi.js` | `MockMarketFeed` singleton `marketFeed`: exports `SYMBOL_TO_TOKEN` (`AAPL→NSE_EQ|INE062A01020`, `MSFT→…INE160A01022`, `TSLA→…INE467I01027`, `NVDA→…INE009A01021`, `AMZN→…INE075A01022`, `BTC` = SBIN key × 90), polls `GET /api/prices` every 2500 ms through `apiFetch`, keeps `prices` (demo symbols) and `keyPrices` (raw instrument keys), diffs prices, notifies subscribers (`subscribe()` returns an unsubscribe fn). `setExtraKeys(keys)` adds the account watchlist to the poll |
| `mockData.js` | `initialTrades` — the 9 demo trades, mirrored by `INITIAL_TRADES` in `journal_service.py` |
| `styles.css` | ~1520 lines: CSS custom properties (`--text-muted`, `--color-danger`, `--border-radius-md`, …), utility classes (`text-up`, `text-down`, `badge`, `pill-option`, `td-mono`), the auth gate, and three responsive breakpoints (1100px / 880px / 520px) plus `@media (hover: none)` |

- **`getMetrics()` is the analytics core:** replay trades chronologically, maintain per-symbol average cost (sign-flip = close), accumulate realized P&L and an `equityCurve`, then derive `winRate`, `profitFactor`, `avgWin`, `avgLoss`, `activePositions`, and `strategyAnalysis` / `emotionAnalysis` (count, wins, net P&L, avg `pfMatrix`/`rsMatrix`/`xPercentage`).
- **`startingBalance` = 100000** lives only in `state.js` (exported, but **not** persisted to localStorage nor stored server-side).
- **Render contract:** templates are built with `innerHTML` string concatenation and user-supplied text is meant to pass through `escapeHtml` (applied in the majority of interpolations, but `innerHTML` is assigned ~38 times against ~18 `escapeHtml` calls — treat escaping as required for any new interpolation). Prices flash `price-up`/`price-down` for 800 ms.
- **Gotcha:** `addTrade`/`editTrade` push a temporary id (`trade_temp_<ts>_<rand>`) and later swap in the server id — anything keyed on ids must tolerate that swap. `editTrade` converts emptied numeric inputs to explicit `null`, which the repositories now honour as a clear (GAP-1b).

### M12 — Tests · `tests/`
| File | Coverage | Style |
| --- | --- | --- |
| `conftest.py` | `install_owner(owner_id)` overrides `get_current_user` + every repository/service factory with memory implementations for that owner; `api` fixture (owner `user-a`, rate-limit buckets reset, `client.repos` exposes the doubles) and `anon_client` (real auth dependency, `AUTH_DISABLED=False`, fake `SUPABASE_URL`/`SUPABASE_ANON_KEY` so no network call is made). Fixtures build a bare `TestClient` so **the lifespan never runs** (no pool, no streamer thread) | fixtures |
| `test_models.py` | Trade/Strategy/Emotion validation, defaults, `gt=0` rejections, `model_dump(exclude_unset=True)` | sync |
| `test_price_cache.py` | get/set, batch defaults, 5-thread concurrent writes, freshness meta / stale flagging | sync + `threading` |
| `test_market_data.py` | `_extract_ltp` across `ltpc` / `marketFF` / `indexFF` / `firstLevelWithGreeks`, `live_feed` → cache, `market_info` ignored, auth gating | sync |
| `test_subscriptions.py` | `diff_subscriptions` both directions + merge, registry union, TTL expiry, `drop_user` | sync |
| `test_repositories.py` | Memory-repo CRUD, case-insensitive duplicate rejection, cascading delete → `Uncategorized` / `Neutral`, clear-on-explicit-null, absent-field untouched, owner isolation | `@pytest.mark.asyncio` (auto mode) |
| `test_api_endpoints.py` | All REST routes through the `api` fixture (memory repos override the factories) | sync TestClient |
| `test_auth.py` | `/health` public, `/auth/config` in both modes, `401` for missing/garbage/expired/wrong-issuer/wrong-audience tokens (RSA keypair + monkeypatched JWKS), HS256 via the legacy secret, dev bypass accepted locally and refused in production, startup guard, cross-tenant `404`s, per-owner duplicate names, per-owner reset & import isolation, trade cap, `429`, watchlist defaults/round-trip/invalid keys/registry publication | sync TestClient |
| `test_postgres.py` | Real Postgres (a session-scoped `pgserver`, or `TEST_DATABASE_URL`): RLS enabled with zero policies, insert order + generated ids, owner isolation, jsonb merge / explicit-null clear / empty patch, id clash gets a fresh id, transactional reset, case-insensitive duplicates, strategy and emotion cascades, watchlist upsert, one-time seeding, unreachable DSN | `@pytest.mark.asyncio` (auto mode) |

- **`pytest.ini` sets `asyncio_mode = auto`**, so `@pytest.mark.asyncio` is optional; `import main` (therefore `asyncpg`) is still required for the API test modules, and `test_postgres.py` downloads nothing - it boots the bundled PostgreSQL 16 binary from the `pgserver` package into `.pgtest/`.
- **Never covered:** the live Supabase project (Auth service, JWKS endpoint, pooler), the real Upstox socket, and all browser behaviour.
- Empirical state in this workspace: **78 tests pass** (`python -m pytest -q`), 14 of them against a real Postgres.

### M13 — Build / Deploy Config
- `requirements.txt` - unpinned, **production only**: `fastapi`, `uvicorn`, `upstox-python-sdk`, `python-dotenv`, `websocket-client`, `asyncpg`, `PyJWT[crypto]`, `pytest`, `pytest-asyncio`, `httpx` (`motor`/`pymongo` are gone). `requirements-dev.txt` adds `pgserver` on top for the Postgres tests - it is kept out of the deploy because Render's default Python outran the package's wheels.
- `vercel.json` - `cleanUrls`, rewrites `/api/:path*` **and** `/auth/config` → `https://stock-journal-xenm.onrender.com/...`, and `/(.*)` → `/static/$1` (Vercel only hosts the UI; the API host is also set in `index.html`). `/auth/config` needs its own rule because it does not live under `/api`.
- `.gitignore` - `.env`, caches, venvs, `.pgtest/` (the pgserver data directory), `journal_db.json` (a leftover from the pre-Mongo JSON store).

---

## 3. Cross-Module Flows

**A. First page load / overview read**
`auth.js initAuth()` → `GET /auth/config` → supabase-js client + `onAuthStateChange` (or a dev-mode pass-through when the API answers `provider: "none"`) → `authReady` resolves → `app.js` boots → `state.js loadState()` → `apiFetch('/api/journal')` (adds the bearer token) → `get_journal_service` builds 3 owner-scoped Postgres repos → `JournalService.get_journal_overview()` → `seed_if_empty(owner_id)` (may write defaults **for that account only**) → 3 × `SELECT ... WHERE owner_id = $1` → envelope → `onLoad` callback → `app.js updateAllViews()` + `loadWatchlist()` → `getMetrics(currentPrices)`.

**B. Trade CRUD (dual path)**
`app.js` form → `stateManager.addTrade/editTrade/deleteTrade` → local mutation + `localStorage` → `POST /api/trades` | `PUT /api/trades/{id}` | `DELETE /api/trades/{id}` → `PostgresTradeRepository` (direct, service layer skipped). `/api/journal/reset` and `/api/journal/import` reach the same tables through `JournalService`.

**C. Live price path**
Upstox WS (or Mock) → `on_tick_received` → `price_cache.set_price` → `GET /api/prices?tokens=…` (polled every 2.5 s by `marketFeed`) → `MockMarketFeed.prices` → subscriber in `app.js` → `currentPrices` → ticker DOM + `getMetrics(currentPrices)` → unrealized P&L and equity re-render.

**D. Reset / import / clear**
Reset: `stateManager.resetToMock()` sets `initialTrades` locally then `POST /api/journal/reset` → `reset_to_mock()` wipes + reseeds all three tables (one transaction each).
Import: `state.js importData()` parses JSON → `POST /api/journal/import` → endpoint calls `reset_trades` / `reset_strategies` / `reset_emotions` with **unvalidated** dicts.
Clear: `clearAll()` → `POST /api/journal/import` with `trades: []` but the current strategies/emotions.

**E. Watchlist → streamer subscription**
`GET /api/watchlist` (boot / after each journal load) → `PostgresWatchlistRepository.get_keys()` (falls back to `settings.get_tokens()`) → `subscriptions.set_user_keys(userId, keys)` → registry `snapshot()` inside the daemon's sync thread → `diff_subscriptions(subscribed, wanted)` → `streamer.update_subscriptions(wanted)` (or a forced reconnect when it returns `False`) → ticks land in `price_cache` → the SPA's next `GET /api/prices` poll includes those keys → `marketFeed.keyPrices` → `updateCustomWatchPrices()` repaints the row. `PUT /api/watchlist` follows the same path after persisting.

---

## 4. Conventions

**Backend**
- Layering: `endpoints → service → repository interface → concrete repository`. Endpoints must stay thin; no DB calls outside repositories.
- Dependency factories live in the endpoint module and are named `get_<thing>_repo` / `get_journal_service`, taking `pool: asyncpg.Pool = Depends(get_pool)`; this naming is what the tests override.
- Everything in the data path is `async`; the only sync code is the streamer thread and `PriceCache`.
- Responses use the `{"success", "data" | "message"}` envelope; failures use `HTTPException(status_code, detail)`.
- Booleans returned by repositories mean "did it happen" (`add_*`/`delete_*`), and endpoints convert `False` into 400/404.
- Repository methods speak `dict`/`list[str]`; Pydantic models are an API-boundary concern only.
- **`owner_id` is never a SQL parameter of convenience:** it comes from the constructor and is always `$1`. A new query without `WHERE owner_id = $1` is a tenancy bug.
- Module-level constants hold seeds and taxonomy (`DEFAULT_*`, `INITIAL_TRADES`) — extend those, don't scatter literals.
- SQL lives in `app/repositories/postgres/` only. Values are bind parameters; the sole interpolations are table/column names taken from validated constants.
- Logging via `logging.getLogger("<area>")` (`server`, `database`, `journal-service`, `streamer.mock`, `streamer.upstox`) with f-string messages.
- Module/section banners are `# ====` comments; docstrings appear on endpoint functions and interface methods only.

**Frontend**
- ES modules, no framework, no bundler; singletons exported at module end (`stateManager`, `marketFeed`).
- State changes are local-first and optimistic; server sync is fire-and-forget `.catch(err => console.error(...))`. No await/rollback.
- All server calls go through `apiFetch()` from `static/api.js` (it owns the base URL, the bearer token and the `401` handling); never call `fetch` directly.
- User-supplied text renders through `escapeHtml`; feedback uses `showToast(message, 'success'|'danger')`.
- Sections in `app.js` are delimited by `// ====` banners; keep new render code inside the existing view functions and register listeners in the single `DOMContentLoaded` block.
- Layout rules live in `styles.css`: desktop-first, then the 1100px / 880px / 520px breakpoints. New components need a mobile rule (the sidebar becomes a top bar under 880px, so sidebars/floating panels do not exist there).

---

## 5. Extension Recipes

| Goal | Touch |
| --- | --- |
| New trade field | `app/models/trade.py` (`TradeCreate`, `TradeUpdate`) → `static/app.js` form + table + detail modal → `static/state.js` (`addTrade` normalisation, `getMetrics` if analytical) → seed data in `INITIAL_TRADES` and `static/mockData.js`. No migration: fields live in the `trades.data` jsonb document |
| New REST resource | endpoint module in `app/api/endpoints/` (`APIRouter(dependencies=[Depends(get_current_user)])`) + `include_router(...)` in `app/api/router.py` + interface in `repositories/interfaces/` + `postgres/` & `memory/` implementations (owner in the constructor) + `schema.py` DDL if it needs a table + service method + tests |
| Swap Postgres for another store | implement the four M7 interfaces, then change the `get_*_repo` / `get_journal_service` factories (the only place concretions are named) |
| New market-data provider | implement `IMarketDataStreamer` in `app/streaming/` (+ `update_subscriptions`/`is_connected`), add the branch in `build_streamer()` |
| Change the default watchlist basket | `TOKENS` env/default in `app/core/config.py` and the matching seed prices in `mock_streamer.py`; per-account instruments need no code change (`PUT /api/watchlist`) |
| New dashboard view | `index.html` `.page-view` + `.nav-item[data-view]` → `app.js` renderer + `updateAllViews()` + `pageTitle` switch |
| New default taxonomy entry | `DEFAULT_STRATEGIES` / `DEFAULT_EMOTIONS` in `journal_service.py` **and** the fallback arrays in `static/state.js` |

---

## 6. Known Gaps & Inconsistencies (verified in code)

1. **Repository abstraction is only half-honoured** — trade/strategy/emotion/watchlist endpoints construct `Postgres*Repository` directly; only `journal.py` accepts an interface-typed service. The `memory/` implementations are therefore test-only.
2. **`/api/journal/import` bypasses Pydantic per trade** — it now guards the payload shape and the trade cap, but individual dicts still skip validation, `html.escape` and `BUY/SELL` normalisation (open question GAP-2).
3. **Pool creation and schema bootstrap failures are swallowed at startup** — the process still boots, `/health` reports `database: unavailable` and data routes answer `503`. That is a clear-enough signal, but it is not a crash.
4. **Seeding is a side effect of `GET /api/journal`**; a fresh account served by any other endpoint returns empty tables (open question GAP-4).
5. **Rate limits and caps are process-local** — a restart refills the sliding-window budget, and a second Render instance would enforce its own; moving them to Postgres/Redis is the upgrade path.
6. **`PriceCache` staleness is flagged, not enforced** — `meta.stale` reports dead feeds, but the UI does not yet render a stale indicator and values are never dropped.
7. **Analytics exist only in the browser** — no server-side metrics endpoint, so any non-SPA client must re-implement `getMetrics()` (fairly intricate average-cost replay).
8. **Duplicated seed data** (`INITIAL_TRADES` in Python vs `initialTrades` in JS) and **duplicated default taxonomy** (three places).
9. **Streamer is process-local** — multi-instance or serverless deployment silently breaks live prices; the "LIVE FEED ACTIVE" badge is static markup, but `GET /health` now exposes the truth (`streamer.connected`, `prices_fresh`).
10. **The demo tickers still map US symbols onto NSE instrument keys** (BTC scaled ×90) — cosmetic, but it means the dashboard watchlist and the Upstox feed disagree about what "AAPL" is. Real symbols go through the per-account watchlist.
11. **Unpinned `requirements.txt`** — no lockfile, so `upstox-python-sdk`/`asyncpg` behaviours can drift.
12. **Sign-in is email + password only** — no magic link, no OAuth provider, no password-recovery flow. Supabase's **Confirm email** switch must stay off, or a new account cannot sign in until it follows the emailed link (see `production_deployment_guide.md`).
13. **The schema is created by the app, not by migrations** — `ensure_schema()` is idempotent DDL executed at boot. A destructive change needs a hand-written statement, and there is no migration history; adding a column to a jsonb document needs nothing at all.
14. **RLS is enabled with no policies** — deliberate (the backend is the only client), but it means the tables are invisible to anon/PostgREST; exposing them to the browser later needs policies, not just disabling RLS.
15. **`/auth/config` lives outside `/api`** — any new public router needs its own `vercel.json` rewrite, or the static site 404s on it while the Render host works fine.

---

## 7. Glossary

- **PF Matrix / RS Matrix / X Percentage** — user-entered journal metrics (profit factor, relative strength, risk allocation %) averaged per strategy/emotion in analytics.
- **Instrument key** — Upstox identifier of the form `NSE_EQ|<ISIN>` (e.g. `NSE_EQ|INE062A01020` = SBIN); replaces the old numeric Angel One tokens everywhere (`TOKENS`, `price_cache` keys, frontend map). Upstox already delivers rupees, no paise conversion needed.
- **custom_id** — dropped from storage; the `trades.id` text column now holds the public id, so an imported `trade_1` keeps its name and only a clash is re-minted as a uuid.
- **Seeding** — writing `DEFAULT_*` + `INITIAL_TRADES` when a table is empty.
- **Mock mode** — `MOCK_STREAMER=true` or missing credentials; synthetic ticks replace the broker feed.
- **`owner_id`** — the tenancy key: the Supabase `sub` claim (a UUID, or `DEV_USER_ID` in bypass mode). Stamped on insert, filtered on every read, never accepted from a client.
- **Access token** — the short-lived Supabase token the browser attaches as a bearer header; verified locally against the cached JWKS (or the legacy HS256 secret), never stored by this app. supabase-js refreshes it in the background.
- **Watchlist** — the per-account list of instrument keys streamed on the shared socket (`watchlists` table + `SubscriptionRegistry`).

---

## 8. Test Map (what to run)

```powershell
pip install -r requirements-dev.txt                  # app deps + pgserver for the Postgres tests
python -m pytest -q                                  # full suite: 78 tests
python -m pytest tests/test_postgres.py -q           # real Postgres only (pgserver, no network)
python -m pytest tests/test_auth.py -q               # auth + tenancy contract only
python -m pytest tests/test_models.py -q             # pure validation, no infra

$env:AUTH_DISABLED="true"; $env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/postgres"; python main.py
```

`http://localhost:8000/` serves the SPA (with `AUTH_DISABLED=true` the gate hides itself and no token is sent), `http://localhost:8000/docs` the auto-generated OpenAPI UI, and `http://localhost:8000/health` the streamer/auth/database snapshot. Local dev needs *some* Postgres behind `DATABASE_URL` - without it every data route answers `503` while `/health` and the SPA still load.

---

## 9. Related Documents

| Document | Read it for |
| --- | --- |
| `docs/codebase_knowledge.md` (this file) | Module boundaries, invariants, gotchas, extension recipes |
| `docs/architecture.md` | HLD diagram, sequence workflows, class diagrams, SOLID mapping, Postgres schema, deployment topology |
| `docs/design_decisions_and_tradeoffs.md` | Why polling over WebSockets/SSE/Redis, asyncpg vs an ORM, `threading.Lock` vs `asyncio.Lock`, broker API evaluation |
| `docs/file_by_file_design_reference.md` | File-by-file narrative design notes |
| `docs/production_deployment_guide.md` | Env var matrix, Render + Vercel steps, keep-alive, troubleshooting |
