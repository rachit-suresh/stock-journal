# Codebase Knowledge Base

A module-oriented knowledge map of `stock-journal`, distilled from the code itself (not from intent docs).
Use it as the entry point before changing code; use the documents in [§9](#9-related-documents) for narrative depth.

**Fastest orientation:** `main.py` → `app/api/endpoints/*` (guarded by `app/core/security.py`) → `app/services/journal_service.py` → `app/repositories/{interfaces,mongo,memory}` → `static/api.js` → `static/state.js` → `static/app.js`.

---

## 1. System Snapshot

| Dimension | Fact |
| --- | --- |
| What it is | Multi-user trading journal + portfolio dashboard: log trades with strategy / mindset tags, see P&L, equity curve, and per-strategy / per-emotion performance |
| Shape | Single FastAPI process that (a) serves a REST API under `/api`, (b) serves the static SPA from `/`, (c) runs a market-data streamer on a daemon thread |
| Identity | Clerk (hosted sign-in, Google OAuth + email code). The SPA sends `Authorization: Bearer <session JWT>`; the API verifies it statelessly against the Clerk JWKS |
| Tenancy | Every document carries `owner_id` (= Clerk `sub`). Repositories are constructed per request with that owner and filter every read/write; foreign ids answer `404` |
| Persistence | MongoDB via Motor (`stock_journal` DB by default), collections `trades`, `strategies`, `emotions`, `watchlists` |
| Live prices | Broker WebSocket (Upstox market data feed v3) or synthetic mock streamer → in-process `price_cache` → browser polls `GET /api/prices` every 2.5 s. One socket serves every account; a registry diffs the union of watchlists |
| Abuse limits | In-memory sliding-window rate limit on mutations per `(user, ip)` + hard per-user caps checked before insert |
| Frontend | Vanilla ES modules, no build step, Chart.js from CDN. All analytics are computed **client-side**; responsive down to ~360px wide |
| Deployment | Backend/streamer on Render; static UI on Vercel with `/api/*` rewritten to the Render host (`vercel.json`) |
| Tests | pytest (+ pytest-asyncio, TestClient, in-memory repositories), 56 tests |

Two independent state owners exist by design: the server (MongoDB, authoritative) and the browser (`state.js`, optimistic + localStorage fallback). Most surprises in this repo come from that split.

---

## 2. Module Cards

### M0 — Entrypoint & Lifecycle · `main.py`
- **Role:** builds the app, wires middleware, starts/stops infrastructure.
- **Key symbols:** `app`, `lifespan()`, `start_streamer_daemon()`, `run()` (daemon loop), `sync_subscriptions()`.
- **Sequence:** `lifespan` → `validate_auth_config()` (raises only for `AUTH_DISABLED` + `ENV=production`) → `connect_to_mongo()` → `ensure_indexes(get_database())` → `start_streamer_daemon()` (thread, `daemon=True`) → serve → `close_mongo_connection()`.
- **Streamer selection:** mock if `MOCK_STREAMER=true` **or** `UPSTOX_ACCESS_TOKEN` is missing; otherwise `UpstoxMarketStreamer`. Each attempt runs one streamer plus a subscription-sync thread; failures retry after a 10 s sleep.
- **Supervision:** the loop marks `mode`/`connected` via `app/streaming/status.py`, applies `diff_subscriptions()` deltas every `STREAMER_SYNC_SECONDS`, and reconnects once the transport has been connected and then reports closed (the `was_connected` latch exists because Upstox's `connect()` returns immediately).
- **Routing order:** `app.include_router(health.router)` (public) → `app.include_router(api_router)` (authenticated) → `app.mount("/", StaticFiles(directory="static", html=True))`. Health must stay registered *before* the mount or `/health` is swallowed by the static files.
- **Run:** `python main.py` → uvicorn `0.0.0.0:$PORT` (default `8000`), importing `"main:app"` as a string.
- **Gotcha:** the streamer is a *blocking* sync loop inside one process. Scaling past one instance duplicates the subscription; serverless hosts cannot run it.

### M1 — Configuration · `app/core/config.py`
- **Role:** plain `Settings` class (not `pydantic-settings`) reading `.env` via `python-dotenv`, exposed as a module-level singleton `settings`.
- **Environment variables:** `UPSTOX_ACCESS_TOKEN`, `MOCK_STREAMER`, `TOKENS` (default 5 NSE instrument keys `"NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022"` = SBIN, PNB, TCS, INFY, WIPRO), `PRICE_MAX_AGE_SECONDS`, `ALLOWED_ORIGINS` (default `*`), `MONGO_URI`, `MONGO_DB_NAME`, `ENV`, `CLERK_ISSUER`, `AUTH_DISABLED`, `DEV_USER_ID`, `MUTATION_RATE_LIMIT_PER_MINUTE`, `MAX_TRADES_PER_USER`, `MAX_STRATEGIES_PER_USER`, `MAX_EMOTIONS_PER_USER`, `MAX_WATCHLIST_KEYS`, `WATCHLIST_TTL_SECONDS`, `STREAMER_SYNC_SECONDS`.
- **Helpers:** `get_allowed_origins()`, `get_tokens()` (CSV → list, blank-tolerant), `has_upstox_credentials()` (token present), `is_production()`, `auth_mode()` (`clerk` / `dev-bypass`), `validate_auth_config()` (startup guard; a missing `CLERK_ISSUER` only logs, so the API fails closed with `401`s instead of opening itself).
- **Convention:** new config = new `os.getenv` attribute + (if list/CORS-like) a parsing helper. Never read `os.getenv` outside this module.

### M2 — Database Handle · `app/core/database.py`
- **Role:** single Motor client/database holder + FastAPI dependency.
- **Key symbols:** `DatabaseManager` (class-level `client`, `db`), `db_manager`, `connect_to_mongo()`, `close_mongo_connection()`, `get_database()`.
- **Behaviour:** 5 s `serverSelectionTimeoutMS`, then `admin.command('ping')`. **Failures are logged, not raised** — the app still boots with `db_manager.db = None`.
- **Gotcha:** a failed connection therefore surfaces later as a `TypeError`/`None` collection inside a repository constructor (`db["trades"]`), producing a 500 per request instead of a clear startup failure.
- **Extension point:** every endpoint takes `db: AsyncIOMotorDatabase = Depends(get_database)` — tests override the *endpoint* factories, not this one.

### M2b — Identity, Abuse Guards & Indexes · `app/core/{security,limits,indexes}.py`
| File | Role |
| --- | --- |
| `security.py` | `UserContext` (frozen dataclass: `user_id`, `email`, `authenticated`) + `get_current_user` dependency + `verify_session_token`. Bearer token → `PyJWKClient(<CLERK_ISSUER>/.well-known/jwks.json, cache_keys=True, lifespan=3600)` → `jwt.decode(..., algorithms=["RS256","ES256","HS256"], issuer=..., options={"require": ["exp","iss","sub"]})`. The client and its lock are lazy module-level singletons. Every failure maps to `401` with a generic detail (no leak of *why*). With `AUTH_DISABLED=true` it returns `UserContext(settings.DEV_USER_ID, "dev@localhost", authenticated=False)` — but raises `500` if `ENV=production` |
| `limits.py` | `mutation_rate_limit` dependency (60 s sliding window per `"{user_id}:{ip}"`, `429` + `Retry-After: 60`, disabled when `MUTATION_RATE_LIMIT_PER_MINUTE <= 0`), `enforce_cap(current, cap, label)` → `400`, and `reset_rate_limit_buckets()` for tests. Process-local by design |
| `indexes.py` | `ensure_indexes(db)`: partial unique indexes `owner_strategy_unique` / `owner_emotion_unique` / `owner_watchlist_unique` on `(owner_id, name_lower)` / `(owner_id)` with `partialFilterExpression={"owner_id": {"$type": "string"}}`, plus owner-scoped listing indexes. Failures are logged, never raised, so startup cannot be blocked by legacy data |

- **Why the constructors, not the interfaces:** `Mongo*Repository(db, owner_id)` keeps the three ABCs unchanged (the store-swap seam) and lets FastAPI build a fresh owner-scoped repository per request from `get_current_user`.

### M3 — API Router · `app/api/router.py`
- **Role:** one `APIRouter` (`api_router`) with all six endpoint modules mounted under prefix `/api` and tags `Prices`, `Trades`, `Strategies`, `Emotions`, `Watchlist`, `Journal Overview & Maintenance`.
- **Note:** prefixes are declared here, not in the endpoint modules — endpoint files create a bare `APIRouter(dependencies=[Depends(get_current_user)])`. `GET /health` is **not** part of this router: it is public and included separately in `main.py` before the static mount.

### M4 — Endpoint Modules · `app/api/endpoints/`
Each module owns its own dependency factory that *instantiates* a repository from the DB handle.

| File | Routes | Dependency factory | Backing store |
| --- | --- | --- | --- |
| `health.py` | `GET /health` (public, separate router) | none | `status` snapshot + `price_cache` |
| `prices.py` | `GET /api/prices?tokens=a,b` | none (imports the `price_cache` singleton) | in-process cache |
| `trades.py` | `GET /api/trades`, `GET/PUT/DELETE /api/trades/{trade_id}`, `POST /api/trades` | `get_trade_repo` → `MongoTradeRepository(db, user.user_id)` | MongoDB |
| `strategies.py` | `GET/POST /api/strategies`, `DELETE /api/strategies/{name}` | `get_strategy_repo` → `MongoStrategyRepository` | MongoDB |
| `emotions.py` | `GET/POST /api/emotions`, `DELETE /api/emotions/{name}` | `get_emotion_repo` → `MongoEmotionRepository` | MongoDB |
| `watchlist.py` | `GET/PUT /api/watchlist` | `get_watchlist_repo` → `MongoWatchlistRepository` | MongoDB |
| `journal.py` | `GET /api/journal`, `POST /api/journal/reset`, `POST /api/journal/import` (legacy `?action=&type=` routes removed) | `get_journal_service` → `JournalService(Mongo*, Mongo*, Mongo*)` | MongoDB |

- **Authentication:** declared once per router (`APIRouter(dependencies=[Depends(get_current_user)])`), so it cannot be forgotten on a new route. FastAPI caches the dependency, so the JWT is verified once per request and the same `UserContext` feeds the repository factory.
- **Response envelope (universal):** `{"success": true, "data": ...}` for reads/writes, `{"success": true, "message": "..."}` for verbs without a payload.
- **Error idiom:** `raise HTTPException(status_code=404|400, detail="...")`. No try/except in endpoints; unexpected exceptions bubble to FastAPI's 500 handler. Foreign-owner documents answer `404` (never `403`) so ids cannot be probed.
- **Write guards:** `POST /trades`, `POST /strategies`, `POST /emotions` call `enforce_cap(len(await repo.get_all_*()), settings.MAX_*_PER_USER, "Trade")` first; every mutating route also carries `Depends(mutation_rate_limit)`.
- **`prices.py`:** empty/missing `tokens` → `{"data": {}, "meta": {}, "timestamp": <ms epoch>}`. Unknown tokens come back as `100.0` (cache default), never as missing keys, and are flagged `meta[token] = {as_of: null, stale: true}`. Prices are global, not per owner.
- **`journal.py` is one REST surface:** `/journal` (GET only), `/journal/reset`, `/journal/import`. The old query-param compat handlers (`POST ?action=|type=`, `PUT ?id=`, `DELETE ?type=&name=|?id=`) were removed in GAP-3b and now return 405.
- **`/journal/import`** reads a raw `await request.json()` (no Pydantic model) and calls the owner-scoped `reset_*` methods. It now refuses a payload whose `trades`/`strategies`/`emotions` are not lists, or whose trade count exceeds `MAX_TRADES_PER_USER`; individual trade dicts still skip validation and sanitisation (GAP-2).
- **`watchlist.py`:** `GET` returns the stored keys, falling back to `settings.get_tokens()` for an account that never saved one; both verbs call `subscriptions.set_user_keys(user_id, keys)` so the streamer picks the change up on its next sync.
- **Gotcha:** `DELETE /api/strategies/{name}` and `/api/emotions/{name}` take a raw path segment — callers must `encodeURIComponent` (names contain spaces, e.g. `Pullback Support`).

### M5 — Domain Service · `app/services/journal_service.py`
- **Role:** the only place with domain rules: default taxonomy, seeding, overview assembly, reset.
- **Key symbols:** `JournalService`, `DEFAULT_STRATEGIES` (Breakout, Pullback Support, Gap Fill, Trend Continuation, Mean Reversion), `DEFAULT_EMOTIONS` (Disciplined, Confident, Neutral, Anxious, FOMO, Greedy), `INITIAL_TRADES` (9 seed trades, ids `trade_1`–`trade_9`).
- **Constructor takes the three *interfaces*** (`ITradeRepository`, `IStrategyRepository`, `IEmotionRepository`) — the only genuine dependency-inversion point in the app.
- **`seed_if_empty()`** seeds each collection independently, only when empty. It is called from `get_journal_overview()`, i.e. **seeding is a side effect of the first `GET /api/journal`**, not of startup.
- **`get_journal_overview()`** returns `{"trades", "strategies", "emotions"}`; everything else (`add_trade`, `update_trade`, `delete_trade`, `add_strategy`, …) is a one-line pass-through to a repository.
- **`reset_to_mock()`** = reset all three collections to the constants above.
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
- **Consequence:** stored text is HTML-escaped at the boundary, so `&` becomes `&amp;` in MongoDB and the frontend escapes again on render.
- **Convention:** field names are `camelCase` on the wire (`stopLoss`, `pfMatrix`, `xPercentage`) to match the JS frontend — do not rename without touching `static/app.js` and `static/state.js`.

### M7 — Repository Contracts · `app/repositories/interfaces/`
- `ITradeRepository` (ABC): `get_all_trades`, `get_trade_by_id`, `create_trade`, `update_trade`, `delete_trade`, `reset_trades` — all `async`.
- `IStrategyRepository` / `IEmotionRepository`: `get_all_*`, `add_*`, `delete_*`, `reset_*`.
- `IWatchlistRepository`: `get_keys() -> list[str]`, `set_keys(keys) -> list[str]`.
- **Contract detail:** repository methods exchange plain `dict`s / `list[str]`, never Pydantic models, and models are imported by the interface files but unused. **Ownership is not a method parameter** — it is constructor state (`Mongo*Repository(db, owner_id)`), which is what keeps these ABCs stable.
- **Rule of thumb:** a method missing here cannot be reached by the service; adding behaviour means changing the interface **and both implementations** (`mongo/`, `memory/`).

### M8 — MongoDB Implementations · `app/repositories/mongo/`
- **Collections:** `trades`, `strategies`, `emotions`, `watchlists`. Strategy/emotion repos also hold `trades_collection` for cascades; the watchlist repo is one document per owner (`{"owner_id", "keys"}`).
- **Owner scoping:** every repository takes `owner_id` in the constructor (`ValueError` when blank). Every query is `{"$and": [{"owner_id": self.owner_id}, identity]}`; inserts stamp `owner_id` from the server and strip any client-supplied value (`update_trade` strips `owner_id` too, and `_to_trade` pops it so it never leaks into a response).
- **ID translation (trades):** documents keep Mongo `_id`; an optional `custom_id` carries imported ids. Reads map the public id as `doc["id"] = doc.pop("custom_id", str(_id))` and always drop `_id`.
- **Lookup query pattern (repeated in get/update/delete):** `_identity_query(id)` returns `{"$or": [{"_id": ObjectId(id)}, {"custom_id": id}]}` when the id is a valid ObjectId, `{"custom_id": id}` otherwise — wrapped in the owner filter, so a foreign id simply does not match (endpoint turns that into `404`).
- **`create_trade`:** pops incoming `id`; if it is not a valid ObjectId it is stored as `custom_id`; returns the dict with `id` filled in.
- **`update_trade`:** writes the exact keys it is given (`None` included, so a field can be cleared), then re-reads. An empty payload returns the current document.
- **`reset_trades` / `reset_strategies` / `reset_emotions`:** `delete_many({"owner_id": …})` then `insert_many(stamped docs)` — not atomic; a concurrent read during reset sees an empty set for that owner only.
- **Duplicate detection (strategies/emotions):** case-insensitive anchored regex `^escaped$` on `(owner_id, name_lower)` before insert, backed by the partial unique index from `ensure_indexes`; a duplicate-key error raised by a racing insert is caught (`"duplicate key" in str(e).lower()`) and reported as `False`/`400` instead of a `500`.
- **Cascade on delete:** `update_many({"owner_id": …, "strategy": actual_name}, {"$set": {"strategy": "Uncategorized"}})` and the emotion equivalent → `"Neutral"`. Matching uses the *stored* casing, not the requested one.

### M9 — In-Memory Implementations · `app/repositories/memory/`
- **Role:** test doubles / reference implementations of M7. List/dict-backed, fully `async`, no I/O.
- **Constructor signature mirrors Mongo:** `MemoryTradeRepository(owner_id)` / `MemoryStrategyRepository(owner_id, names=None, trade_repo=None)` / `MemoryEmotionRepository(...)` / `MemoryWatchlistRepository(owner_id)`. Stored docs are stripped of `owner_id` and filtered per owner on the way out.
- **`MemoryTradeRepository`:** optional `initial_trades`; `create_trade` mints `trade_mem_<n>` when no `id` is supplied; matches `id` or `custom_id`.
- **`MemoryStrategyRepository` / `MemoryEmotionRepository`:** optional seeded names plus an optional `trade_repo` used to perform the same cascade (loop + `update_trade`) as Mongo.
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
| `index.html` | Shell only (~620 lines): sign-in gate (`#auth-gate` → `#clerk-sign-in`), 5 views (`dashboard`, `tradelog`, `strategies`, `emotions`, `analytics`), 2 modals (add/edit trade, trade detail), toast container, mistake pills, sidebar account row + watchlist add form. Sets `window.FASTAPI_BACKEND_URL` and `window.CLERK_PUBLISHABLE_KEY` before loading modules. Assets are version-tagged `?v=2.5` |
| `auth.js` | Clerk glue: decodes the publishable key into a Frontend API host, injects `clerk.browser.js` with `data-clerk-publishable-key`, `initAuth()` (mount sign-in when there is no session, reload once one appears), `authReady` promise, `getAuthToken()`, `clearLocalJournalKeys()`, `handleUnauthorized()`, `signOut()`, `currentUserEmail()`, `authMode()`. An empty publishable key = dev mode: the gate is skipped and no `Authorization` header is sent |
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
| `conftest.py` | `install_owner(owner_id)` overrides `get_current_user` + every repository/service factory with memory implementations for that owner; `api` fixture (owner `user-a`, rate-limit buckets reset, `client.repos` exposes the doubles) and `anon_client` (real auth dependency, `AUTH_DISABLED=False`, fake `CLERK_ISSUER`). Fixtures build a bare `TestClient` so **the lifespan never runs** (no Mongo, no streamer thread) | fixtures |
| `test_models.py` | Trade/Strategy/Emotion validation, defaults, `gt=0` rejections, `model_dump(exclude_unset=True)` | sync |
| `test_price_cache.py` | get/set, batch defaults, 5-thread concurrent writes, freshness meta / stale flagging | sync + `threading` |
| `test_market_data.py` | `_extract_ltp` across `ltpc` / `marketFF` / `indexFF` / `firstLevelWithGreeks`, `live_feed` → cache, `market_info` ignored, auth gating | sync |
| `test_subscriptions.py` | `diff_subscriptions` both directions + merge, registry union, TTL expiry, `drop_user` | sync |
| `test_repositories.py` | Memory-repo CRUD, case-insensitive duplicate rejection, cascading delete → `Uncategorized` / `Neutral`, clear-on-explicit-null, absent-field untouched, owner isolation | `@pytest.mark.asyncio` (auto mode) |
| `test_api_endpoints.py` | All REST routes through the `api` fixture (memory repos override the factories) | sync TestClient |
| `test_auth.py` | `/health` public, `401` for missing/garbage/expired/wrong-issuer tokens (RSA keypair + monkeypatched JWKS), dev bypass accepted locally and refused in production, startup guard, cross-tenant `404`s, per-owner duplicate names, per-owner reset & import isolation, trade cap, `429`, watchlist defaults/round-trip/invalid keys/registry publication | sync TestClient |

- **`pytest.ini` sets `asyncio_mode = auto`**, so `@pytest.mark.asyncio` is optional; `import main` (therefore `motor`) is still required for the API test modules.
- **Never covered:** live Mongo/Atlas, the real Upstox socket, and all browser behaviour.
- Empirical state in this workspace: **56 tests pass** (`python -m pytest -q`).

### M13 — Build / Deploy Config
- `requirements.txt` — unpinned: `fastapi`, `uvicorn`, `upstox-python-sdk`, `python-dotenv`, `websocket-client`, `motor`, `pymongo`, `PyJWT[crypto]`, `pytest`, `pytest-asyncio`, `httpx`.
- `vercel.json` — `cleanUrls`, rewrite `/api/:path*` → `https://stock-journal-xenm.onrender.com/api/:path*`, and `/(.*)` → `/static/$1` (Vercel only hosts the UI; the API host is also set in `index.html`).
- `.gitignore` — `.env`, caches, venvs, `journal_db.json` (a leftover from the pre-Mongo JSON store).

---

## 3. Cross-Module Flows

**A. First page load / overview read**
`auth.js initAuth()` → Clerk widget (or dev-mode pass-through) → `authReady` resolves → `app.js` boots → `state.js loadState()` → `apiFetch('/api/journal')` (adds the bearer token) → `get_journal_service` builds 3 owner-scoped Mongo repos → `JournalService.get_journal_overview()` → `seed_if_empty(owner_id)` (may write defaults **for that account only**) → 3 `find({"owner_id": …})` → envelope → `onLoad` callback → `app.js updateAllViews()` + `loadWatchlist()` → `getMetrics(currentPrices)`.

**B. Trade CRUD (dual path)**
`app.js` form → `stateManager.addTrade/editTrade/deleteTrade` → local mutation + `localStorage` → `POST /api/trades` | `PUT /api/trades/{id}` | `DELETE /api/trades/{id}` → `MongoTradeRepository` (direct, service layer skipped). The legacy `POST/PUT/DELETE /api/journal?…` comparators reach the same data through `JournalService`.

**C. Live price path**
Upstox WS (or Mock) → `on_tick_received` → `price_cache.set_price` → `GET /api/prices?tokens=…` (polled every 2.5 s by `marketFeed`) → `MockMarketFeed.prices` → subscriber in `app.js` → `currentPrices` → ticker DOM + `getMetrics(currentPrices)` → unrealized P&L and equity re-render.

**D. Reset / import / clear**
Reset: `stateManager.resetToMock()` sets `initialTrades` locally then `POST /api/journal/reset` → `reset_to_mock()` wipes + reseeds all three collections.
Import: `state.js importData()` parses JSON → `POST /api/journal/import` → endpoint calls `reset_trades` / `reset_strategies` / `reset_emotions` with **unvalidated** dicts.
Clear: `clearAll()` → `POST /api/journal/import` with `trades: []` but the current strategies/emotions.

**E. Watchlist → streamer subscription**
`GET /api/watchlist` (boot / after each journal load) → `MongoWatchlistRepository.get_keys()` (falls back to `settings.get_tokens()`) → `subscriptions.set_user_keys(userId, keys)` → registry `snapshot()` inside the daemon's sync thread → `diff_subscriptions(subscribed, wanted)` → `streamer.update_subscriptions(wanted)` (or a forced reconnect when it returns `False`) → ticks land in `price_cache` → the SPA's next `GET /api/prices` poll includes those keys → `marketFeed.keyPrices` → `updateCustomWatchPrices()` repaints the row. `PUT /api/watchlist` follows the same path after persisting.

---

## 4. Conventions

**Backend**
- Layering: `endpoints → service → repository interface → concrete repository`. Endpoints must stay thin; no DB calls outside repositories.
- Dependency factories live in the endpoint module and are named `get_<thing>_repo` / `get_journal_service`, taking `db: AsyncIOMotorDatabase = Depends(get_database)`; this naming is what the tests override.
- Everything in the data path is `async`; the only sync code is the streamer thread and `PriceCache`.
- Responses use the `{"success", "data" | "message"}` envelope; failures use `HTTPException(status_code, detail)`.
- Booleans returned by repositories mean "did it happen" (`add_*`/`delete_*`), and endpoints convert `False` into 400/404.
- Repository methods speak `dict`/`list[str]`; Pydantic models are an API-boundary concern only.
- Module-level constants hold seeds and taxonomy (`DEFAULT_*`, `INITIAL_TRADES`) — extend those, don't scatter literals.
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
| New trade field | `app/models/trade.py` (`TradeCreate`, `TradeUpdate`) → `static/app.js` form + table + detail modal → `static/state.js` (`addTrade` normalisation, `getMetrics` if analytical) → seed data in `INITIAL_TRADES` and `static/mockData.js`. Mongo needs no migration (schemaless) |
| New REST resource | endpoint module in `app/api/endpoints/` (`APIRouter(dependencies=[Depends(get_current_user)])`) + `include_router(...)` in `app/api/router.py` + interface in `repositories/interfaces/` + `mongo/` & `memory/` implementations (owner in the constructor) + service method + tests |
| Swap Mongo for another store | implement the four M7 interfaces, then change the `get_*_repo` / `get_journal_service` factories (the only place concretions are named) |
| New market-data provider | implement `IMarketDataStreamer` in `app/streaming/` (+ `update_subscriptions`/`is_connected`), add the branch in `build_streamer()` |
| Change the default watchlist basket | `TOKENS` env/default in `app/core/config.py` and the matching seed prices in `mock_streamer.py`; per-account instruments need no code change (`PUT /api/watchlist`) |
| New dashboard view | `index.html` `.page-view` + `.nav-item[data-view]` → `app.js` renderer + `updateAllViews()` + `pageTitle` switch |
| New default taxonomy entry | `DEFAULT_STRATEGIES` / `DEFAULT_EMOTIONS` in `journal_service.py` **and** the fallback arrays in `static/state.js` |

---

## 6. Known Gaps & Inconsistencies (verified in code)

1. **Repository abstraction is only half-honoured** — trade/strategy/emotion/watchlist endpoints construct `Mongo*Repository` directly; only `journal.py` accepts an interface-typed service. The `memory/` implementations are therefore test-only.
2. **`/api/journal/import` bypasses Pydantic per trade** — it now guards the payload shape and the trade cap, but individual dicts still skip validation, `html.escape` and `BUY/SELL` normalisation (open question GAP-2).
3. **Mongo connection failure is swallowed at startup**, deferring the failure to per-request 500s.
4. **Seeding is a side effect of `GET /api/journal`**; a fresh account served by any other endpoint returns empty collections (open question GAP-4).
5. **Rate limits and caps are process-local** — a restart refills the sliding-window budget, and a second Render instance would enforce its own; moving them to Mongo/Redis is the upgrade path.
6. **`PriceCache` staleness is flagged, not enforced** — `meta.stale` reports dead feeds, but the UI does not yet render a stale indicator and values are never dropped.
7. **Analytics exist only in the browser** — no server-side metrics endpoint, so any non-SPA client must re-implement `getMetrics()` (fairly intricate average-cost replay).
8. **Duplicated seed data** (`INITIAL_TRADES` in Python vs `initialTrades` in JS) and **duplicated default taxonomy** (three places).
9. **Streamer is process-local** — multi-instance or serverless deployment silently breaks live prices; the "LIVE FEED ACTIVE" badge is static markup, but `GET /health` now exposes the truth (`streamer.connected`, `prices_fresh`).
10. **The demo tickers still map US symbols onto NSE instrument keys** (BTC scaled ×90) — cosmetic, but it means the dashboard watchlist and the Upstox feed disagree about what "AAPL" is. Real symbols go through the per-account watchlist.
11. **Unpinned `requirements.txt`** — no lockfile, so `upstox-python-sdk`/`motor` behaviours can drift.
12. **The Clerk publishable key is baked into `index.html`** — fine (it is public), but rotating Clerk instances means a redeploy of the static site, not just an env change.
13. **The Clerk instance must be a Development instance, or a production instance on an owned domain** — a production key points at `clerk.<domain>`, and `clerk.<project>.vercel.app` cannot serve Clerk because Vercel's `*.vercel.app` certificate covers one label only (TLS handshake refused → no `clerk.browser.js`, no JWKS → every `/api` call `401`). See `design_decisions_and_tradeoffs.md` §11.
14. **The clerk-js major must be pinned in `auth.js` (`CLERK_JS_MAJOR`)** — the CDN path `…/npm/@clerk/clerk-js@<major>/dist/clerk.browser.js` is instance-managed, and an old major mounts a widget that then refuses to sign in ("outdated version of Clerk"). The `@latest` alias is a trap: it still resolves to the legacy 4.x bundle.
15. **Clerk v6 needs two bundles, not one** — `…/npm/@clerk/ui@1/dist/ui.browser.js` must load before `clerk.browser.js`, and `Clerk.load()` must receive `{ ui: { ClerkUI: window.__internal_ClerkUICtor } }`. Loading clerk-js alone looks successful (the script and its chunks 200) but leaves `#clerk-sign-in` empty and makes every `mount*()` throw "Clerk was not loaded with Ui components".

---

## 7. Glossary

- **PF Matrix / RS Matrix / X Percentage** — user-entered journal metrics (profit factor, relative strength, risk allocation %) averaged per strategy/emotion in analytics.
- **Instrument key** — Upstox identifier of the form `NSE_EQ|<ISIN>` (e.g. `NSE_EQ|INE062A01020` = SBIN); replaces the old numeric Angel One tokens everywhere (`TOKENS`, `price_cache` keys, frontend map). Upstox already delivers rupees, no paise conversion needed.
- **custom_id** — Mongo-side field preserving non-ObjectId ids (`trade_1`) so imports/exports keep their identity.
- **Seeding** — writing `DEFAULT_*` + `INITIAL_TRADES` when a collection is empty.
- **Mock mode** — `MOCK_STREAMER=true` or missing credentials; synthetic ticks replace the broker feed.
- **`owner_id`** — the tenancy key: the Clerk `sub` claim (or `DEV_USER_ID` in bypass mode). Stamped on insert, filtered on every read, never accepted from a client.
- **Session JWT** — the short-lived Clerk token the browser attaches as a bearer header; verified locally against the cached JWKS, never stored by this app.
- **Watchlist** — the per-account list of instrument keys streamed on the shared socket (`watchlists` collection + `SubscriptionRegistry`).

---

## 8. Test Map (what to run)

```powershell
pip install -r requirements.txt                      # includes PyJWT[crypto] for token verification
python -m pytest -q                                  # full suite (56 tests, no Mongo / no network)
python -m pytest tests/test_auth.py -q               # auth + tenancy contract only
python -m pytest tests/test_models.py -q             # pure validation, no infra

$env:AUTH_DISABLED="true"; python main.py            # local dev: no Clerk needed, SPA talks to :8000
```

`http://localhost:8000/` serves the SPA (leave `CLERK_PUBLISHABLE_KEY` empty so the UI runs in dev mode), `http://localhost:8000/docs` the auto-generated OpenAPI UI, and `http://localhost:8000/health` the streamer/auth snapshot.

---

## 9. Related Documents

| Document | Read it for |
| --- | --- |
| `docs/codebase_knowledge.md` (this file) | Module boundaries, invariants, gotchas, extension recipes |
| `docs/architecture.md` | HLD diagram, sequence workflows, class diagrams, SOLID mapping, Mongo schema, deployment topology |
| `docs/design_decisions_and_tradeoffs.md` | Why polling over WebSockets/SSE/Redis, Motor vs PyMongo, `threading.Lock` vs `asyncio.Lock`, broker API evaluation |
| `docs/file_by_file_design_reference.md` | File-by-file narrative design notes |
| `docs/production_deployment_guide.md` | Env var matrix, Render + Vercel steps, keep-alive, troubleshooting |
