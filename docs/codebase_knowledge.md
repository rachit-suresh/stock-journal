# Codebase Knowledge Base

A module-oriented knowledge map of `stock-journal`, distilled from the code itself (not from intent docs).
Use it as the entry point before changing code; use the documents in [§9](#9-related-documents) for narrative depth.

**Fastest orientation:** `main.py` → `app/api/endpoints/*` → `app/services/journal_service.py` → `app/repositories/{interfaces,mongo,memory}` → `static/state.js` → `static/app.js`.

---

## 1. System Snapshot

| Dimension | Fact |
| --- | --- |
| What it is | Personal trading journal + portfolio dashboard: log trades with strategy / mindset tags, see P&L, equity curve, and per-strategy / per-emotion performance |
| Shape | Single FastAPI process that (a) serves a REST API under `/api`, (b) serves the static SPA from `/`, (c) runs a market-data streamer on a daemon thread |
| Persistence | MongoDB via Motor (`stock_journal` DB by default), collections `trades`, `strategies`, `emotions` |
| Live prices | Broker WebSocket (Upstox market data feed v3) or synthetic mock streamer → in-process `price_cache` → browser polls `GET /api/prices` every 2.5 s |
| Frontend | Vanilla ES modules, no build step, Chart.js from CDN. All analytics are computed **client-side** |
| Deployment | Backend/streamer on Render; static UI on Vercel with `/api/*` rewritten to the Render host (`vercel.json`) |
| Tests | pytest (+ pytest-asyncio, TestClient, in-memory repositories) |

Two independent state owners exist by design: the server (MongoDB, authoritative) and the browser (`state.js`, optimistic + localStorage fallback). Most surprises in this repo come from that split.

---

## 2. Module Cards

### M0 — Entrypoint & Lifecycle · `main.py`
- **Role:** builds the app, wires middleware, starts/stops infrastructure.
- **Key symbols:** `app`, `lifespan()`, `start_streamer_daemon()`.
- **Sequence:** `lifespan` → `connect_to_mongo()` → `start_streamer_daemon()` (thread, `daemon=True`) → serve → `close_mongo_connection()`.
- **Streamer selection:** mock if `MOCK_STREAMER=true` **or** `UPSTOX_ACCESS_TOKEN` is missing; otherwise `UpstoxMarketStreamer`. The thread loops forever and retries after a 10 s sleep on any exception.
- **Routing order:** `app.include_router(api_router)` **before** `app.mount("/", StaticFiles(directory="static", html=True))` — that ordering is what keeps `/api/*` from being swallowed by the static mount.
- **Run:** `python main.py` → uvicorn `0.0.0.0:$PORT` (default `8000`), importing `"main:app"` as a string.
- **Gotcha:** the streamer is a *blocking* sync loop inside one process. Scaling past one instance duplicates the subscription; serverless hosts cannot run it.

### M1 — Configuration · `app/core/config.py`
- **Role:** plain `Settings` class (not `pydantic-settings`) reading `.env` via `python-dotenv`, exposed as a module-level singleton `settings`.
- **Environment variables:** `UPSTOX_ACCESS_TOKEN`, `MOCK_STREAMER`, `TOKENS` (default 5 NSE instrument keys `"NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022"` = SBIN, PNB, TCS, INFY, WIPRO), `ALLOWED_ORIGINS` (default `*`), `MONGO_URI` (default `mongodb://localhost:27017`), `MONGO_DB_NAME` (default `stock_journal`).
- **Helpers:** `get_allowed_origins()`, `get_tokens()` (CSV → list, blank-tolerant), `has_upstox_credentials()` (token present).
- **Convention:** new config = new `os.getenv` attribute + (if list/CORS-like) a parsing helper. Never read `os.getenv` outside this module.

### M2 — Database Handle · `app/core/database.py`
- **Role:** single Motor client/database holder + FastAPI dependency.
- **Key symbols:** `DatabaseManager` (class-level `client`, `db`), `db_manager`, `connect_to_mongo()`, `close_mongo_connection()`, `get_database()`.
- **Behaviour:** 5 s `serverSelectionTimeoutMS`, then `admin.command('ping')`. **Failures are logged, not raised** — the app still boots with `db_manager.db = None`.
- **Gotcha:** a failed connection therefore surfaces later as a `TypeError`/`None` collection inside a repository constructor (`db["trades"]`), producing a 500 per request instead of a clear startup failure.
- **Extension point:** every endpoint takes `db: AsyncIOMotorDatabase = Depends(get_database)` — tests override the *endpoint* factories, not this one.

### M3 — API Router · `app/api/router.py`
- **Role:** one `APIRouter` (`api_router`) with all five endpoint modules mounted under prefix `/api` and tags `Prices`, `Trades`, `Strategies`, `Emotions`, `Journal Overview & Maintenance`.
- **Note:** prefixes are declared here, not in the endpoint modules — endpoint files create a bare `APIRouter()`.

### M4 — Endpoint Modules · `app/api/endpoints/`
Each module owns its own dependency factory that *instantiates* a repository from the DB handle.

| File | Routes | Dependency factory | Backing store |
| --- | --- | --- | --- |
| `prices.py` | `GET /api/prices?tokens=a,b` | none (imports the `price_cache` singleton) | in-process cache |
| `trades.py` | `GET /api/trades`, `GET/PUT/DELETE /api/trades/{trade_id}`, `POST /api/trades` | `get_trade_repo` → `MongoTradeRepository` | MongoDB |
| `strategies.py` | `GET/POST /api/strategies`, `DELETE /api/strategies/{name}` | `get_strategy_repo` → `MongoStrategyRepository` | MongoDB |
| `emotions.py` | `GET/POST /api/emotions`, `DELETE /api/emotions/{name}` | `get_emotion_repo` → `MongoEmotionRepository` | MongoDB |
| `journal.py` | `GET /api/journal`, `POST /api/journal/reset`, `POST /api/journal/import` (legacy `?action=&type=` routes removed) | `get_journal_service` → `JournalService(Mongo*, Mongo*, Mongo*)` | MongoDB |

- **Response envelope (universal):** `{"success": true, "data": ...}` for reads/writes, `{"success": true, "message": "..."}` for verbs without a payload.
- **Error idiom:** `raise HTTPException(status_code=404|400, detail="...")`. No try/except in endpoints; unexpected exceptions bubble to FastAPI's 500 handler.
- **`prices.py`:** empty/missing `tokens` → `{"data": {}, "meta": {}, "timestamp": <ms epoch>}`. Unknown tokens come back as `100.0` (cache default), never as missing keys, and are flagged `meta[token] = {as_of: null, stale: true}`.
- **`journal.py` is one REST surface:** `/journal` (GET only), `/journal/reset`, `/journal/import`. The old query-param compat handlers (`POST ?action=|type=`, `PUT ?id=`, `DELETE ?type=&name=|?id=`) were removed in GAP-3b and now return 405.
- **`/journal/import`** reads a raw `await request.json()` (no Pydantic model) and calls `service.trade_repo.reset_*` directly — it bypasses validation, sanitisation and the service methods.
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
- **Contract detail:** repository methods exchange plain `dict`s / `list[str]`, never Pydantic models, and models are imported by the interface files but unused.
- **Rule of thumb:** a method missing here cannot be reached by the service; adding behaviour means changing the interface **and both implementations** (`mongo/`, `memory/`).

### M8 — MongoDB Implementations · `app/repositories/mongo/`
- **Collections:** `trades`, `strategies`, `emotions`. Strategy/emotion repos also hold `trades_collection` for cascades.
- **ID translation (trades):** documents keep Mongo `_id`; an optional `custom_id` carries imported ids. Reads map the public id as `doc["id"] = doc.pop("custom_id", str(_id))` and always drop `_id`.
- **Lookup query pattern (repeated in get/update/delete):**
  `{"$or": [{"_id": ObjectId(id)}, {"custom_id": id}]} if ObjectId.is_valid(id) else {"custom_id": id}` — so both ObjectId strings and seed ids like `trade_1` resolve.
- **`create_trade`:** pops incoming `id`; if it is not a valid ObjectId it is stored as `custom_id`; returns the dict with `id` filled in.
- **`update_trade`:** strips `None` values (`{k: v for k, v in ... if v is not None}`) before `$set`, then re-reads. An all-`None` payload simply returns the current document.
- **`reset_trades` / `reset_strategies` / `reset_emotions`:** `delete_many({})` then `insert_many(...)` — not atomic; a concurrent read during reset sees an empty collection.
- **Duplicate detection (strategies/emotions):** case-insensitive anchored regex `^escaped$` with `$options: "i"`, executed before insert. No unique index exists, so concurrent adds can still both succeed.
- **Cascade on delete:** `update_many({"strategy": actual_name}, {"$set": {"strategy": "Uncategorized"}})` and the emotion equivalent → `"Neutral"`. Matching uses the *stored* casing, not the requested one.
- **Gotcha:** because updates drop `None`, **optional fields can never be cleared through the API** (sending `stopLoss: null` is a no-op), which is exactly what the edit form produces when a field is emptied.

### M9 — In-Memory Implementations · `app/repositories/memory/`
- **Role:** test doubles / reference implementations of M7. List-backed, fully `async`, no I/O.
- **`MemoryTradeRepository`:** optional `initial_trades`; `create_trade` mints `trade_mem_<n>` when no `id` is supplied; matches `id` or `custom_id`.
- **`MemoryStrategyRepository` / `MemoryEmotionRepository`:** optional seeded names plus an optional `trade_repo` used to perform the same cascade (loop + `update_trade`) as Mongo.
- **Gotcha:** the application never injects these — only `tests/test_api_endpoints.py` does, via `app.dependency_overrides`.

### M10 — Streaming Subsystem · `app/streaming/`
| File | Role |
| --- | --- |
| `base_streamer.py` | `IMarketDataStreamer` ABC: `authenticate() -> bool`, `connect_and_stream(tokens) -> None`, `on_tick_received(token, ltp) -> None` — all **synchronous** |
| `price_cache.py` | `PriceCache` + module singleton `price_cache`; stores `(ltp, timestamp)` per instrument key under a `threading.Lock`; `get_price`/`get_batch_prices` return the last known LTP (default `100.0` only for never-seen keys); `get_batch_meta` reports `as_of`/`stale` against `PRICE_MAX_AGE_SECONDS` (default 30) |
| `mock_streamer.py` | Seeds the 5 default instrument keys (SBIN 650, PNB 80, TCS 3500, INFY 1500, WIPRO 450); every 2 s nudges up to 2 random keys by ±0.4 % and calls `on_tick_received` |
| `upstox_streamer.py` | `upstox_client.Configuration` + `access_token` → `MarketDataStreamerV3` (official `upstox-python-sdk`); subscribes `tokens` in `"ltpc"` mode on open; decoded v3 messages are `{"type": "live_feed", "feeds": {"<instrument_key>": {…}}}` and `_extract_ltp` reads `ltpc` at `feeds[key]`, `fullFeed.marketFF/.indexFF`, or `firstLevelWithGreeks`; `market_info` messages are ignored; `upstox_client` is imported lazily so mock mode works without the SDK installed |

- **Credentials:** `UPSTOX_ACCESS_TOKEN` holds the Upstox **Analytics Access Token** — read-only, one-year validity, accepted by the Market Data and Streaming APIs (no OAuth app, client id/secret or daily refresh). `authenticate()` only checks presence, and a revoked/expired token surfaces as a WebSocket error logged by `on_error` (the daemon then retries every 10 s).

- **Threading contract:** the streamer thread writes to `price_cache`; the asyncio event loop only reads it. That is why a `threading.Lock` (not an `asyncio.Lock`) is used — never `await` inside `PriceCache`.
- **Extension point:** a new provider = implement `IMarketDataStreamer` + add a branch in `start_streamer_daemon()`; `on_tick_received` is already the cache sink.
- **Gotcha:** a token that never ticks reports `100.0`; it is now distinguishable because `meta[token].stale` is `true` (same flag used for a dead feed).

### M11 — Static SPA · `static/`
| File | Role / key facts |
| --- | --- |
| `index.html` | Shell only (≈590 lines): 5 views (`dashboard`, `tradelog`, `strategies`, `emotions`, `analytics`), 2 modals (add/edit trade, trade detail), toast container, mistake pills. Sets `window.FASTAPI_BACKEND_URL` (default `https://stock-journal-xenm.onrender.com`) before loading modules. Assets are version-tagged `?v=2.3` |
| `state.js` | `StateManager` singleton `stateManager`: `loadState()` (GET `/api/journal`, then localStorage keys `stock_journal_trades|strategies|emotions`, then `initialTrades`), CRUD with **optimistic local mutation + fire-and-forget `fetch`**, `exportData()/importData()` (POST `/api/journal/import`), `resetToMock()` (POST `/api/journal/reset`), `clearAll()`, and the analytics engine `getMetrics(currentPrices)` |
| `app.js` | ~1130 lines of DOM/render + event wiring: `escapeHtml`, `showToast`, `initCharts` (Chart.js: `equityChart`, `allocationChart`), `renderDashboardView/renderTradeLogView/renderStrategiesView/renderEmotionsView/renderAnalyticsView`, `updateAllViews()`, modal open/close, `startMarketTickerSubscription()`, and every listener inside one `DOMContentLoaded` block |
| `mockApi.js` | `MockMarketFeed` singleton `marketFeed`: maps symbols → broker tokens (`AAPL→3045, MSFT→2885, TSLA→11536, NVDA→1594, AMZN→3456, BTC→3045×90`), polls `GET /api/prices` every 2500 ms, diffs prices, notifies subscribers (`subscribe()` returns an unsubscribe fn) |
| `mockData.js` | `initialTrades` — the 9 demo trades, mirrored by `INITIAL_TRADES` in `journal_service.py` |
| `styles.css` | ~995 lines, CSS custom properties (`--text-muted`, `--color-danger`, `--border-radius-md`, …) + utility classes (`text-up`, `text-down`, `badge`, `pill-option`, `td-mono`) |

- **`getMetrics()` is the analytics core:** replay trades chronologically, maintain per-symbol average cost (sign-flip = close), accumulate realized P&L and an `equityCurve`, then derive `winRate`, `profitFactor`, `avgWin`, `avgLoss`, `activePositions`, and `strategyAnalysis` / `emotionAnalysis` (count, wins, net P&L, avg `pfMatrix`/`rsMatrix`/`xPercentage`).
- **`startingBalance` = 100000** lives only in `state.js` (exported, but **not** persisted to localStorage nor stored server-side).
- **Render contract:** templates are built with `innerHTML` string concatenation and user-supplied text is meant to pass through `escapeHtml` (applied in the majority of interpolations, but `innerHTML` is assigned ~38 times against ~18 `escapeHtml` calls — treat escaping as required for any new interpolation). Prices flash `price-up`/`price-down` for 800 ms.
- **Gotcha:** `addTrade`/`editTrade` push a temporary id (`trade_temp_<ts>_<rand>`) and later swap in the server id — anything keyed on ids must tolerate that swap. `editTrade` converts emptied numeric inputs to explicit `null`, which the repositories now honour as a clear (GAP-1b).

### M12 — Tests · `tests/`
| File | Coverage | Style |
| --- | --- | --- |
| `test_models.py` | Trade/Strategy/Emotion validation, defaults, `gt=0` rejections, `model_dump(exclude_unset=True)` | sync |
| `test_price_cache.py` | get/set, batch defaults, 5-thread concurrent writes, freshness meta / stale flagging | sync + `threading` |
| `test_market_data.py` | `_extract_ltp` across `ltpc` / `marketFF` / `indexFF` / `firstLevelWithGreeks`, `live_feed` → cache, `market_info` ignored, auth gating | sync |
| `test_repositories.py` | Memory-repo CRUD, case-insensitive duplicate rejection, cascading delete → `Uncategorized` / `Neutral`, clear-on-explicit-null, absent-field untouched | `@pytest.mark.asyncio` (auto mode) |
| `test_api_endpoints.py` | All REST routes through `TestClient`, with `app.dependency_overrides` swapping in memory repos for `get_journal_service`, `get_trade_repo`, `get_strategy_repo`, `get_emotion_repo` | sync TestClient |

- **`pytest.ini` sets `asyncio_mode = auto`** (no `conftest.py`), so `@pytest.mark.asyncio` is no longer required; `import main` (therefore `motor`) is still required for the API test module.
- **Never covered:** Mongo repositories, live Upstox wiring, `/api/journal/import`, and all frontend code.
- Empirical state in this workspace: `pip install motor pytest-asyncio` → **33 tests pass** (models, price cache + freshness, memory repos, Upstox feed parsing, API CRUD/journal/prices).

### M13 — Build / Deploy Config
- `requirements.txt` — unpinned: `fastapi`, `uvicorn`, `upstox-python-sdk`, `python-dotenv`, `websocket-client`, `motor`, `pymongo`, `pytest`, `pytest-asyncio`, `httpx`.
- `vercel.json` — `cleanUrls`, rewrite `/api/:path*` → `https://stock-journal-xenm.onrender.com/api/:path*`, and `/(.*)` → `/static/$1` (Vercel only hosts the UI; the API host is also hardcoded in `index.html`).
- `.gitignore` — `.env`, caches, venvs, `journal_db.json` (a leftover from the pre-Mongo JSON store).

---

## 3. Cross-Module Flows

**A. First page load / overview read**
`state.js loadState()` → `GET /api/journal` → `get_journal_service` builds 3 Mongo repos → `JournalService.get_journal_overview()` → `seed_if_empty()` (may write defaults) → 3 `find({})` → envelope → `onLoad` callback → `app.js updateAllViews()` → `getMetrics(currentPrices)`.

**B. Trade CRUD (dual path)**
`app.js` form → `stateManager.addTrade/editTrade/deleteTrade` → local mutation + `localStorage` → `POST /api/trades` | `PUT /api/trades/{id}` | `DELETE /api/trades/{id}` → `MongoTradeRepository` (direct, service layer skipped). The legacy `POST/PUT/DELETE /api/journal?…` comparators reach the same data through `JournalService`.

**C. Live price path**
Upstox WS (or Mock) → `on_tick_received` → `price_cache.set_price` → `GET /api/prices?tokens=…` (polled every 2.5 s by `marketFeed`) → `MockMarketFeed.prices` → subscriber in `app.js` → `currentPrices` → ticker DOM + `getMetrics(currentPrices)` → unrealized P&L and equity re-render.

**D. Reset / import / clear**
Reset: `stateManager.resetToMock()` sets `initialTrades` locally then `POST /api/journal/reset` → `reset_to_mock()` wipes + reseeds all three collections.
Import: `state.js importData()` parses JSON → `POST /api/journal/import` → endpoint calls `reset_trades` / `reset_strategies` / `reset_emotions` with **unvalidated** dicts.
Clear: `clearAll()` → `POST /api/journal/import` with `trades: []` but the current strategies/emotions.

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
- All backend URLs derive from `window.FASTAPI_BACKEND_URL`; never hardcode a second host.
- User-supplied text renders through `escapeHtml`; feedback uses `showToast(message, 'success'|'danger')`.
- Sections in `app.js` are delimited by `// ====` banners; keep new render code inside the existing view functions and register listeners in the single `DOMContentLoaded` block.

---

## 5. Extension Recipes

| Goal | Touch |
| --- | --- |
| New trade field | `app/models/trade.py` (`TradeCreate`, `TradeUpdate`) → `static/app.js` form + table + detail modal → `static/state.js` (`addTrade` normalisation, `getMetrics` if analytical) → seed data in `INITIAL_TRADES` and `static/mockData.js`. Mongo needs no migration (schemaless) |
| New REST resource | endpoint module in `app/api/endpoints/` + `include_router(...)` in `app/api/router.py` + interface in `repositories/interfaces/` + `mongo/` & `memory/` implementations + service method + tests |
| Swap Mongo for another store | implement the three M7 interfaces, then change the `get_*_repo` / `get_journal_service` factories (the only place concretions are named) |
| New market-data provider | implement `IMarketDataStreamer` in `app/streaming/`, add the branch in `start_streamer_daemon()` |
| Change the watchlist | `TOKENS` env/default in `app/core/config.py` + `mock_streamer.py` seed prices + `mockApi.js` `SYMBOL_TO_TOKEN` (keep the three in sync) |
| New dashboard view | `index.html` `.page-view` + `.nav-item[data-view]` → `app.js` renderer + `updateAllViews()` + `pageTitle` switch |
| New default taxonomy entry | `DEFAULT_STRATEGIES` / `DEFAULT_EMOTIONS` in `journal_service.py` **and** the fallback arrays in `static/state.js` |

---

## 6. Known Gaps & Inconsistencies (verified in code)

1. **Repository abstraction is only half-honoured** — trade/strategy/emotion endpoints construct `Mongo*Repository` directly; only `journal.py` accepts an interface-typed service. The `memory/` implementations are therefore test-only.
2. **`/api/journal/import` bypasses Pydantic entirely** — no validation, no `html.escape`, no `BUY/SELL` normalisation for imported data.
3. **Mongo connection failure is swallowed at startup**, deferring the failure to per-request 500s.
4. **Seeding is a side effect of `GET /api/journal`**; a fresh database served by any other endpoint returns empty collections.
5. **No indexes / unique constraints** — accepted for single-user scale (GAP-6a); duplicate strategy/emotion names are only prevented by a read-then-insert race, so a unique index can be added later without touching endpoints.
6. **`PriceCache` staleness is flagged, not enforced** — `meta.stale` reports dead feeds, but the UI does not yet render a stale indicator and values are never dropped.
7. **Analytics exist only in the browser** — no server-side metrics endpoint, so any non-SPA client must re-implement `getMetrics()` (fairly intricate average-cost replay).
8. **Duplicated seed data** (`INITIAL_TRADES` in Python vs `initialTrades` in JS) and **duplicated default taxonomy** (three places).
9. **Streamer is process-local** — multi-instance or serverless deployment silently breaks live prices; the "LIVE FEED ACTIVE" badge is static markup, not health-checked.
10. **Hardcoded symbol→instrument-key map** maps US tickers onto NSE instrument keys (and scales BTC by 90×) — changing the watchlist means editing `mockApi.js`, `TOKENS`/`mock_streamer.py` seeds together.
11. **Unpinned `requirements.txt`** — no lockfile, so `upstox-python-sdk`/`motor` behaviours can drift.

---

## 7. Glossary

- **PF Matrix / RS Matrix / X Percentage** — user-entered journal metrics (profit factor, relative strength, risk allocation %) averaged per strategy/emotion in analytics.
- **Instrument key** — Upstox identifier of the form `NSE_EQ|<ISIN>` (e.g. `NSE_EQ|INE062A01020` = SBIN); replaces the old numeric Angel One tokens everywhere (`TOKENS`, `price_cache` keys, frontend map). Upstox already delivers rupees, no paise conversion needed.
- **custom_id** — Mongo-side field preserving non-ObjectId ids (`trade_1`) so imports/exports keep their identity.
- **Seeding** — writing `DEFAULT_*` + `INITIAL_TRADES` when a collection is empty.
- **Mock mode** — `MOCK_STREAMER=true` or missing credentials; synthetic ticks replace the broker feed.

---

## 8. Test Map (what to run)

```powershell
pip install -r requirements.txt
python -m pytest -q                                  # full suite (needs motor + pytest-asyncio)
python -m pytest tests/test_models.py -q             # pure validation, no infra
python main.py                                       # API + SPA on :8000
```

`http://localhost:8000/` serves the SPA, `http://localhost:8000/docs` the auto-generated OpenAPI UI.

---

## 9. Related Documents

| Document | Read it for |
| --- | --- |
| `docs/codebase_knowledge.md` (this file) | Module boundaries, invariants, gotchas, extension recipes |
| `docs/architecture.md` | HLD diagram, sequence workflows, class diagrams, SOLID mapping, Mongo schema, deployment topology |
| `docs/design_decisions_and_tradeoffs.md` | Why polling over WebSockets/SSE/Redis, Motor vs PyMongo, `threading.Lock` vs `asyncio.Lock`, broker API evaluation |
| `docs/file_by_file_design_reference.md` | File-by-file narrative design notes |
| `docs/production_deployment_guide.md` | Env var matrix, Render + Vercel steps, keep-alive, troubleshooting |
