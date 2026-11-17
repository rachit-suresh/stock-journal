# Stock Journal — System Specification

- **Version:** 1.4
- **Baseline compiled:** 2026-11-03, from the code (authoritative) and `docs/*.md` (context)
- **Revised:** 2026-11-17 — GAP decisions recorded in §11 (GAP-1b, GAP-3b, GAP-5b, GAP-6a, GAP-8b)
- **Revised:** 2026-11-18 — v1.2: Upstox **Analytics token** replaces the daily-OAuth-token model (GAP-7 closed). v1.3: public site with open signup — Clerk identity + owner-scoped data added as §10. v1.4: §10 **implemented** (Clerk JWT verification, `owner_id` tenancy, per-user watchlist GAP-9b, abuse caps GAP-10b), GAP-11 closed as not applicable (no live data yet)
- **Governance:** this file is the source of truth. The process for changing it lives in `.qoder/rules/spec-driven-development.md`; every change is logged in `AUDIT.md`.
- **Reading the IDs:** requirements are `SPEC-<AREA>-<n>` (CFG config, MDL models, API endpoints, SVC service, PER persistence, MKT market data, FE frontend, AUTH identity/tenancy, NF non-functional). Items listed in §11 are open spec questions (`GAP-*`) and are **user decisions**, not code tasks.

---

## 1. System Overview

- **SPEC-S-1** One FastAPI process provides: a REST API under `/api`, the static SPA mounted at `/` (mounted *after* the API router), and a market-data streamer running on a daemon thread. `main.py`
- **SPEC-S-2** Persistence is MongoDB via Motor; database name from `MONGO_DB_NAME`; collections `trades`, `strategies`, `emotions`. `app/core/database.py`
- **SPEC-S-3** Live prices come from the Upstox market data feed v3 WebSocket, or a synthetic mock generator; both feed an in-process `price_cache` that `GET /api/prices` serves; the browser polls it. `app/streaming/`
- **SPEC-S-4** Portfolio analytics (P&L, win rate, profit factor, per-tag breakdowns) are computed **client-side** by the SPA. The server has no analytics endpoint. `static/state.js`
- **SPEC-S-5** Deployment: backend + streamer on Render, static UI on Vercel; `vercel.json` rewrites `/api/*` to the Render host and everything else to `/static/*`. `vercel.json`

---

## 2. Configuration (`app/core/config.py`)

- **SPEC-CFG-1** A single `Settings` class reads `.env` (python-dotenv) into class attributes; `settings` is a module singleton. No `os.getenv` outside this module.
- **SPEC-CFG-2** Environment variables:

  | Variable | Purpose | Default |
  | --- | --- | --- |
  | `UPSTOX_ACCESS_TOKEN` | Upstox **Analytics Access Token** — read-only, 1-year validity, covers Market Data + Streaming; renew before its expiry date (no OAuth app required) | `""` |
  | `MOCK_STREAMER` | Force mock market data | `false` |
  | `TOKENS` | CSV of Upstox instrument keys to stream | `NSE_EQ\|INE062A01020,NSE_EQ\|INE160A01022,NSE_EQ\|INE467I01027,NSE_EQ\|INE009A01021,NSE_EQ\|INE075A01022` (SBIN, PNB, TCS, INFY, WIPRO) |
  | `PRICE_MAX_AGE_SECONDS` | Age after which a cached price is reported as stale | `30` |
  | `ALLOWED_ORIGINS` | CORS origins; must list the Vercel origin in production (SPEC-AUTH-13) | `*` |
  | `MONGO_URI` | MongoDB connection string (Atlas SRV URI in production) | `mongodb://localhost:27017` |
  | `MONGO_DB_NAME` | Database name | `stock_journal` |
  | `ENV` | `development` / `production`; guards `AUTH_DISABLED` and CORS defaults | `development` |
  | `CLERK_ISSUER` | Clerk instance issuer URL; JWKS derived as `<issuer>/.well-known/jwks.json`. Must be the instance's TLS-valid Frontend API host — a `clerk.<project>.vercel.app` host is unreachable (see DD §11) | `""` |
  | `AUTH_DISABLED` | Dev-only bypass of JWT verification (refused when `ENV=production`) | `false` |
  | `DEV_USER_ID` | Subject used for every request while `AUTH_DISABLED=true` | `dev-local` |
  | `MUTATION_RATE_LIMIT_PER_MINUTE` | Per-user, per-IP ceiling on POST/PUT/DELETE; `<= 0` disables (SPEC-AUTH-15) | `60` |
  | `MAX_TRADES_PER_USER` | Hard cap on documents one account may own; `<= 0` disables (SPEC-AUTH-16) | `2000` |
  | `MAX_STRATEGIES_PER_USER` | Same, for strategies | `50` |
  | `MAX_EMOTIONS_PER_USER` | Same, for emotions | `50` |
  | `MAX_WATCHLIST_KEYS` | Instruments one account may subscribe to (SPEC-AUTH-14) | `25` |
  | `WATCHLIST_TTL_SECONDS` | How long a watchlist keeps its feed slots without a request | `3600` |
  | `STREAMER_SYNC_SECONDS` | Interval of the subscription sync / reconnect watchdog | `15` |

- **SPEC-CFG-3** `get_allowed_origins()`: blank or `*` → `["*"]`; otherwise trimmed CSV list.
- **SPEC-CFG-4** `get_tokens()`: trimmed CSV list, blanks dropped; blank string → `[]`.
- **SPEC-CFG-5** Streamer mode selection: mock when `MOCK_STREAMER=true` **or** `UPSTOX_ACCESS_TOKEN` is empty; otherwise Upstox. `main.py`
- **SPEC-CFG-6** Port comes from `PORT` (default `8000`), bound to `0.0.0.0`.
- **SPEC-CFG-7** `is_production()` (`ENV` case-insensitive `production`) gates the auth bypass; `auth_mode()` returns `clerk` or `dev-bypass` for `/health`; `validate_auth_config()` runs in the lifespan — it raises `RuntimeError` when `AUTH_DISABLED` is combined with `ENV=production`, and only *logs* a missing `CLERK_ISSUER` so the server still boots (and then answers `401` to everything) rather than opening the API by accident.

---

## 3. Data Models (`app/models/`)

- **SPEC-MDL-1** `TradeCreate` fields:

  | Field | Type | Required | Constraint / Default |
  | --- | --- | --- | --- |
  | `symbol` | str | yes | stripped, upper-cased |
  | `side` | str | no | `BUY`/`SELL` (case-insensitive in, upper-cased out); default `BUY` |
  | `price` | float | yes | `> 0` |
  | `shares` | int | yes | `> 0` |
  | `stopLoss` | float | no | `None` |
  | `pfMatrix` | float | no | `None` — profit-factor ratio metric |
  | `rsMatrix` | float | no | `None` — relative-strength metric |
  | `xPercentage` | float | no | `None` — risk allocation % |
  | `strategy` | str | no | default `Uncategorized` |
  | `emotion` | str | no | default `Neutral` |
  | `mistakes` | list[str] | no | default `["None"]` |
  | `notes` | str | no | default `""` |
  | `date` | str | no | default current UTC ISO-8601 |

- **SPEC-MDL-2** Text sanitization: `notes`, `strategy`, `emotion` are stripped then `html.escape`d server-side; persisted values may contain HTML entities; the client escapes again on render.
- **SPEC-MDL-3** `TradeUpdate`: every field optional; endpoints serialize with `model_dump(exclude_unset=True)` so absent fields are not sent.
- **SPEC-MDL-4** Wire format is **camelCase** (`stopLoss`, `pfMatrix`, `rsMatrix`, `xPercentage`) because the frontend consumes it directly; renaming requires a coordinated frontend change.
- **SPEC-MDL-5** `StrategyCreate` / `EmotionCreate`: `name: str`, `min_length=1`.
- **SPEC-MDL-6** API responses are typed (GAP-8b): `TradeResponse` is the read model for every trade endpoint — it mirrors the wire fields **without** the input validators, because persisted text is already escaped and re-sanitizing on output would double-escape it. Envelope, price-meta and journal models live in `app/models/responses.py`.
- **SPEC-MDL-7** `WatchlistUpdate` (`app/models/watchlist.py`): `keys: list[str]`, each stripped and upper-cased, validated against `^[A-Z0-9]{2,12}_[A-Z0-9]{2,8}\|[A-Z0-9]{4,20}$` (e.g. `NSE_EQ|INE062A01020`); duplicates collapse, an invalid key or more than `MAX_WATCHLIST_KEYS` entries is a `422` from the validator. `WatchlistResponse` is the envelope `{"success": true, "data": [key, …]}`.

---

## 4. API (`app/api/endpoints/`)

- **SPEC-API-0** Universal response envelope: `{"success": true, "data": …}` (`DataResponse`) for payloads; `{"success": true, "message": …}` (`MessageResponse`) for verbs without one. Failures raise `HTTPException` with status `400` (invalid/duplicate/missing param) or `404` (not found). Every endpoint declares a Pydantic `response_model`, so OpenAPI is fully typed (GAP-8b).
- **SPEC-API-1** `GET /api/prices?tokens=a,b` → `{"success", "data": {token: ltp}, "timestamp": <epoch ms>, "meta": {token: {"as_of": <epoch ms|null>, "stale": bool}}}`. `data` keeps the last known LTP for every requested token (unknown tokens return `100.0`, never missing keys); `meta.stale` is `true` when the tick is older than `PRICE_MAX_AGE_SECONDS` or the token was never seen (GAP-5b). Empty/missing `tokens` → empty `data` and `meta`.
- **SPEC-API-2** Trades: `GET /api/trades`; `GET /api/trades/{id}` (404 if absent); `POST /api/trades` (validates via `TradeCreate`); `PUT /api/trades/{id}` (validates via `TradeUpdate`, `exclude_unset`; 404); `DELETE /api/trades/{id}` (404).
- **SPEC-API-3** Strategies: `GET /api/strategies` (list of names); `POST /api/strategies` (`{"name"}`; duplicate case-insensitive or blank → 400); `DELETE /api/strategies/{name}` (404; cascades trades to `Uncategorized`).
- **SPEC-API-4** Emotions: same shape; cascade target `Neutral`.
- **SPEC-API-5** `GET /api/journal` → `{"trades", "strategies", "emotions"}`; **seeds empty collections as a side effect** (SPEC-SVC-3).
- **SPEC-API-6** `POST /api/journal/reset` → restores the caller's three collections to the seed constants (SPEC-SVC-4).
- **SPEC-API-7** `POST /api/journal/import` accepts raw JSON `{trades, strategies, emotions}` and bulk-replaces **the caller's** collections. It now rejects a non-list payload and an oversized trade array (`> MAX_TRADES_PER_USER`) with `400`, but individual trade dicts still bypass Pydantic validation and sanitization — documented current behavior; see GAP-2.
- **SPEC-API-8** Legacy query-param compat routes are **removed** (GAP-3b). `POST`/`PUT`/`DELETE /api/journal?action=|type=|id=` no longer exist and return `405` (no handler for that method on the path); all mutations go through the typed REST routes in SPEC-API-2/3/4/6.
- **SPEC-API-9** Dependencies are injected via factory functions declared in each endpoint module (`get_trade_repo`, `get_strategy_repo`, `get_emotion_repo`, `get_watchlist_repo`, `get_journal_service`); these names are the test-override surface. Each factory depends on `get_current_user` and passes its `user_id` into the repository (SPEC-AUTH-6). Authentication is declared once per router (`APIRouter(dependencies=[Depends(get_current_user)])`); FastAPI caches the dependency, so one JWT verification serves the whole request.
- **SPEC-API-10** `GET /health` is the only unauthenticated route (a separate router included *before* the static mount): `{"status": "ok", "env": <ENV>, "auth": "clerk" | "dev-bypass", "streamer": {"mode", "connected", "changed_at"}, "prices_fresh": bool}`. Used by Render health checks and to diagnose a silent feed (SPEC-AUTH-2, SPEC-MKT-2, SPEC-MKT-8).
- **SPEC-API-11** `GET /api/watchlist` → the caller's instrument keys; an account that never saved one receives the shared `TOKENS` defaults (SPEC-MKT-7). `PUT /api/watchlist` replaces the list (body `{"keys": [...]}`, `WatchlistUpdate`), is rate-limited, and both verbs republish the keys to `subscriptions` so the streamer picks them up on its next sync. `GET /api/prices` stays global (SPEC-AUTH-12).

---

## 5. Service Layer (`app/services/journal_service.py`)

- **SPEC-SVC-1** Default taxonomy: strategies `Breakout, Pullback Support, Gap Fill, Trend Continuation, Mean Reversion`; emotions `Disciplined, Confident, Neutral, Anxious, FOMO, Greedy`.
- **SPEC-SVC-2** `INITIAL_TRADES`: 9 demo trades with ids `trade_1`–`trade_9`; mirrored by `static/mockData.js`.
- **SPEC-SVC-3** `seed_if_empty()` seeds each collection **only if that owner's collection is empty**, invoked from `get_journal_overview()` — i.e. seeding is a side effect of the first `GET /api/journal` of a new account, not of startup (see GAP-4).
- **SPEC-SVC-4** `reset_to_mock()` replaces **only the caller's** documents with the SPEC-SVC-1/2 constants; other accounts are untouched (SPEC-AUTH-10).
- **SPEC-SVC-5** `JournalService` is the only interface-typed component; all other CRUD methods are pass-throughs to repositories.
- **SPEC-SVC-6** Trade/strategy/emotion endpoints bypass the service and construct Mongo repositories directly — accepted current architecture; the interfaces + `memory/` implementations are exercised via test overrides only.

---

## 6. Persistence (`app/repositories/mongo/`)

- **SPEC-PER-1** Repositories exchange plain `dict` / `list[str]` only — never Pydantic models.
- **SPEC-PER-2** Public trade id = `custom_id` when present, else `str(_id)`; `_id` is never exposed.
- **SPEC-PER-3** Trade lookups accept either an ObjectId string or a `custom_id` (`$or` query; `custom_id` only when the id is not a valid ObjectId).
- **SPEC-PER-4** `create_trade` pops an incoming `id`; non-ObjectId ids are stored as `custom_id`.
- **SPEC-PER-5** Update semantics (GAP-1b): the endpoint sends only keys present in the request body (`exclude_unset`). A key **absent** from the body stays unchanged; a key explicitly set to `null` **clears** that field (Mongo `$set` writes `null`, the memory repo overwrites the key). An empty body returns the current document unchanged. `id`/`custom_id` are never written by an update.
- **SPEC-PER-6** `reset_trades` / `reset_strategies` / `reset_emotions`: `delete_many({"owner_id": …})` then `insert_many` of stamped docs — non-atomic; concurrent reads during reset may see an empty collection (accepted).
- **SPEC-PER-7** Duplicate strategy/emotion detection is a case-insensitive anchored regex read before insert on `(owner_id, name_lower)`, **backed by a unique index** (GAP-6 re-decided). Index creation is best-effort at startup (`app/core/indexes.py`); a duplicate-key error is still caught and reported as `400`/`False`, so a doc that raced past the pre-check cannot surface as a `500`.
- **SPEC-PER-8** Cascades: deleting a strategy reassigns matching trades to `Uncategorized`; deleting an emotion reassigns to `Neutral`. Matching uses the *stored* casing.
- **SPEC-PER-9** In-memory repositories (`app/repositories/memory/`) mirror this contract and are the reference/test doubles (test-only in practice, SPEC-SVC-6).

---

## 7. Market Data (`app/streaming/`)

- **SPEC-MKT-1** `IMarketDataStreamer` (sync ABC): `authenticate() -> bool`, `connect_and_stream(tokens) -> None`, `on_tick_received(token, ltp) -> None`, plus the two optional capabilities `update_subscriptions(tokens) -> bool` (apply a delta; `False` = transport cannot re-subscribe, caller must reconnect) and `is_connected() -> bool` (defaults `True`). Every implementation writes ticks into `price_cache` via `on_tick_received`.
- **SPEC-MKT-2** `price_cache` (GAP-5b): module singleton storing `(ltp, unix_ts)` per token under a `threading.Lock` (writer = streamer thread, reader = asyncio loop). `get_price`/`get_batch_prices` return the last known LTP and fall back to `100.0` only when the token was never seen (GAP-5c was not taken). `get_batch_meta` reports `as_of` + `stale`, where `stale` means the entry is older than `max_age_seconds` (`PRICE_MAX_AGE_SECONDS`, default 30) — stale entries are flagged, never dropped. `has_fresh_data()` answers "did any tick land inside the window" for `/health`.
- **SPEC-MKT-3** `UpstoxMarketStreamer`: official `upstox-python-sdk`; `Configuration` + access token → `MarketDataStreamerV3`; subscribes `TOKENS` in `"ltpc"` mode on open; decodes v3 messages of the form `{"type": "live_feed", "feeds": {"<instrument_key>": …}}`; LTP is read from `feeds[key].ltpc`, falling back to `fullFeed.marketFF` / `fullFeed.indexFF` / `firstLevelWithGreeks`; `market_info` messages are ignored; `upstox_client` is imported lazily so mock mode runs without the SDK. Auth uses the account-level **Analytics token** (SPEC-CFG-2): read-only, valid one year, accepted by the Market Data and Streaming APIs — so there is no OAuth app, no client id/secret and no daily refresh (GAP-7 closed). `authenticate()` checks token presence only; a revoked or expired token logs a WebSocket error and the daemon retries every 10 s.
- **SPEC-MKT-4** `MockMarketStreamer`: seeds the 5 default instrument keys (SBIN 650, PNB 80, TCS 3500, INFY 1500, WIPRO 450); every 2 s mutates up to 2 random keys by ±0.4 %. A watchlist key it does not know is seeded lazily at `100.0` so the UI shows a value instead of a hole.
- **SPEC-MKT-5** The default basket now lives in one place (`TOKENS`, exposed by `settings.get_tokens()`). `static/mockApi.js` keeps its own *display* symbol→key map for the six demo tickers; everything else in the UI is driven by the per-account watchlist (SPEC-MKT-7), so adding an instrument no longer needs a code change.
- **SPEC-MKT-6** Instrument keys have the form `<SEGMENT>|<ISIN>` (e.g. `NSE_EQ|INE062A01020` = SBIN). Upstox delivers rupees; no unit conversion is applied.
- **SPEC-MKT-7** One socket serves every account. `SubscriptionRegistry` (`app/streaming/subscriptions.py`) holds the default basket plus each account's saved keys with a `touch` timestamp; `snapshot()` prunes accounts idle for `WATCHLIST_TTL_SECONDS` and returns the sorted union. The streamer daemon diffs that union against what it subscribed (`diff_subscriptions(current, wanted)`) every `STREAMER_SYNC_SECONDS` and applies `subscribe`/`unsubscribe` on the live transport.
- **SPEC-MKT-8** Supervision (`main.py`): the daemon owns one streamer instance per attempt, publishes `mode`/`connected` through `app/streaming/status.py` for `/health`, and reconnects when the transport reports closed — Upstox's `connect()` returns immediately, so a `was_connected` latch distinguishes "closed" from "never opened". A failed `update_subscriptions` also forces a reconnect.

---

## 8. Frontend (`static/`)

- **SPEC-FE-1** Two state owners: the server (Mongo, authoritative) and `stateManager` (optimistic local-first + localStorage fallback, fire-and-forget sync). Keys: `stock_journal_trades`, `stock_journal_strategies`, `stock_journal_emotions`.
- **SPEC-FE-2** `loadState()`: `GET /api/journal` → localStorage → `initialTrades` (mockData.js).
- **SPEC-FE-3** CRUD is local-first; the backend call is fire-and-forget. New trades get a temp id (`trade_temp_<ts>_<rand>`) swapped for the server id on success — all id-keyed UI must tolerate the swap.
- **SPEC-FE-4** `getMetrics()` replays trades chronologically: per-symbol average cost (sign flip = close), realized/unrealized P&L, equity curve from `startingBalance`, `winRate`, `profitFactor` (Infinity when no losses and profit > 0, 1 when both are 0), `avgWin`/`avgLoss`, `activePositions`, and per-strategy / per-emotion aggregates (count, wins, net P&L, avg `pfMatrix`/`rsMatrix`/`xPercentage`).
- **SPEC-FE-5** `startingBalance` = 100000, defined client-side only (exported, not persisted, not stored server-side).
- **SPEC-FE-6** `marketFeed` (`static/mockApi.js`) polls `GET /api/prices` every 2500 ms through `apiFetch`. The token set is the union of `SYMBOL_TO_TOKEN` (the six demo tickers mapped onto NSE keys; BTC = SBIN key × 90) and the account's watchlist keys (`extraKeys`, SPEC-FE-12). Demo prices land in `prices`, raw keys in `keyPrices`.
- **SPEC-FE-7** Rendering: `innerHTML` string templates; user text passes through `escapeHtml` (required for any new interpolation). Feedback via toasts.
- **SPEC-FE-8** Views: dashboard, tradelog, strategies, emotions, analytics — switched via `.nav-item[data-view]`; add/edit-trade and trade-detail modals.
- **SPEC-FE-9** Backend base URL = `window.FASTAPI_BACKEND_URL` (set in `index.html`); never hardcode a second host. It is read only inside `static/api.js`.
- **SPEC-FE-12** The dashboard watchlist shows the six demo tickers plus the account's saved instrument keys (rendered as `ticker-key` rows with a remove button). `loadWatchlist()` runs at boot and after every journal load; the add form and the remove buttons call `PUT /api/watchlist` through `saveWatchlist()`, and a `422` surfaces the server detail in a toast instead of a silent failure. Custom rows refresh from `keyPrices` on every poll (`updateCustomWatchPrices`).
- **SPEC-FE-13** The UI must be usable on a phone: `@media (max-width: 1100px)` collapses the grids to one column, `(max-width: 880px)` turns the sidebar into a stacked top bar (brand → scrollable tab strip → action strip) with body scrolling, full-screen modal sheets, horizontally scrollable tables, 16px form text (no iOS zoom-on-focus) and ≥40px touch targets, and `(max-width: 520px)` stacks the metric cards and header actions. `(hover: none)` disables hover-only affordances.

---

## 9. Non-Functional

- **SPEC-NF-1** Security: server-side validation + `html.escape` on text (SPEC-MDL-2); client-side `escapeHtml`; every `/api/*` request authenticated (SPEC-AUTH-2); CORS restricted by `ALLOWED_ORIGINS` with `allow_credentials=False` (bearer tokens travel in headers, so no cookie credentials are needed). Import endpoint validates the payload shape and the trade cap but not each trade (GAP-2).
- **SPEC-NF-2** Everything in the request/data path is `async`; the only sync code is the streamer thread and `PriceCache`. Never `await` inside `PriceCache`.
- **SPEC-NF-3** Logging: `logging.getLogger("<area>")` (`server`, `database`, `journal-service`, `streamer.upstox`, `streamer.mock`, `streamer`, `auth`, `limits`) with f-strings.
- **SPEC-NF-4** Tests: pytest + pytest-asyncio + TestClient, with `asyncio_mode = auto` in `pytest.ini`. `tests/conftest.py` provides `install_owner(owner_id)` (overrides the identity + repository factories) plus the `api` / `anon_client` fixtures; the fixtures never enter the lifespan, so no Mongo or streamer thread starts. Covered: models, `price_cache` incl. freshness, subscription diffing/TTL, memory repositories incl. clear-on-null and owner scoping, Upstox `_extract_ltp` parsing, API CRUD/journal/prices, JWT accept/reject paths (RSA keypair + fake JWKS, expired and wrong-issuer tokens), dev bypass incl. prod refusal, cross-tenant `404`, per-owner duplicates and reset, caps, `429`, journal import guards and the watchlist routes. Not covered: live Mongo/Atlas wiring, live Upstox socket, browser behaviour.
- **SPEC-NF-5** `requirements.txt` is unpinned (accepted); no lockfile.

---

## 10. Authentication & Multi-Tenancy (implemented — v1.4)

Decision 2026-11-18: the site is public with **open signup**; identity is **Clerk** (Google OAuth + email code) and data stays in the existing **MongoDB Atlas** cluster. Deployment remains Vercel (static) + Render (API + streamer). Chosen over a Supabase/Postgres migration: no repo rewrite, and the three repository interfaces remain the seam if the store ever changes.

- **SPEC-AUTH-1** Identity provider is Clerk. The SPA loads `@clerk/clerk-js` and reads the publishable key from `window.CLERK_PUBLISHABLE_KEY` (set in `static/index.html` alongside `FASTAPI_BACKEND_URL`). Enabled strategies: Google OAuth and email code. This app never stores passwords or session tokens of its own.
- **SPEC-AUTH-2** Every `/api/*` route requires `Authorization: Bearer <Clerk session JWT>`; missing, malformed or expired → `401` with the standard envelope. `GET /health` is the only public route (new, see SPEC-API-10).
- **SPEC-AUTH-3** Verification is stateless: `PyJWT` + `PyJWKClient` against `<CLERK_ISSUER>/.well-known/jwks.json`, validating signature, `iss`, `exp` and `nbf`. No local session store, no token refresh server-side; the SDK refreshes on the client.
- **SPEC-AUTH-4** `get_current_user` (FastAPI dependency) returns `{user_id, email?}` from the `sub`/`email` claims. `sub` is the tenancy key and never changes for an account. Email is display-only and is not persisted by this app.
- **SPEC-AUTH-5** Dev escape hatch: `AUTH_DISABLED=true` short-circuits the dependency to a fixed subject `dev-local`. Settings **must refuse to start** with `AUTH_DISABLED=true` when `ENV=production`. Tests set the override explicitly rather than relying on config.
- **SPEC-AUTH-6** All three collections carry `owner_id`. Every repository read and write is filtered by the caller's `owner_id`; documents owned by someone else are reported as `404`, never `403`, so ids cannot be probed.
- **SPEC-AUTH-7** `owner_id` is assigned server-side on insert and is **not** part of `TradeCreate`; a client-supplied `owner_id` is ignored.
- **SPEC-AUTH-8** Strategy/emotion uniqueness is per owner: duplicate detection compares `(owner_id, case-insensitive name)`, backed by a unique index on `(owner_id, name_lower)`. This supersedes GAP-6's "(a) no index".
- **SPEC-AUTH-9** Cascades (strategy→`Uncategorized`, emotion→`Neutral`) are scoped to the caller's `owner_id`.
- **SPEC-AUTH-10** Seeding and reset are per user: `seed_if_empty(owner_id)` runs on the first `GET /api/journal` of a new account (SPEC-SVC-3 unchanged in shape), and `/api/journal/reset` + `/import` only touch the caller's documents.
- **SPEC-AUTH-11** Closed as not applicable (GAP-11): the app has never run against a live Atlas database, so no pre-v1.3 ownerless documents exist. If that ever changes, such documents are invisible to every account (the partial unique indexes deliberately ignore them) until claimed by a one-off script.
- **SPEC-AUTH-12** `GET /api/prices` stays global and read-only: market data is not user data. The streamer and `price_cache` remain process-wide singletons; tenancy must not touch them.
- **SPEC-AUTH-13** CORS in production lists the Vercel origin explicitly; `ALLOWED_ORIGINS=*` is a development-only default. Bearer tokens mean `allow_credentials=False`, which is also required by the CORS spec whenever the allowed origin is `*`.
- **SPEC-FE-10** All HTTP goes through one `apiFetch(path, options)` helper (`static/api.js`): it awaits `authReady`, attaches `Authorization: Bearer <token>` when a session exists, sets `Content-Type: application/json` for bodies, and on `401` signs the user out (dev mode only logs a warning). The 11 existing `fetch` call sites in `state.js`/`mockApi.js` were migrated to it.
- **SPEC-FE-11** Sign-out clears the `stock_journal_*` localStorage keys before reload, so a shared device never shows the previous account's journal (SPEC-FE-1 keys).
- **SPEC-NF-6** JWT verification is cached per process: `PyJWKClient(cache_keys=True, lifespan=3600)` fetches JWKS once and refreshes on key rotation, so a request costs local verification only. The verifier and its lock are created lazily.
- **SPEC-AUTH-14** Each account owns one watchlist document (`watchlists` collection, `owner_id` unique) holding up to `MAX_WATCHLIST_KEYS` instrument keys; the account that never saved one is served the shared `TOKENS` default basket. Watchlists feed the shared market-data socket (SPEC-MKT-7 / SPEC-MKT-8), not the price cache's tenancy.
- **SPEC-AUTH-15** Mutating requests (`POST`/`PUT`/`DELETE`) are rate-limited per `(user_id, client_ip)` with a 60-second sliding window of `MUTATION_RATE_LIMIT_PER_MINUTE` requests, answering `429` + `Retry-After: 60`. Counters are process-local (`app/core/limits.py`); a restart refills the budget, and multiple instances would each hold their own.
- **SPEC-AUTH-16** Hard caps (`MAX_TRADES_PER_USER`, `MAX_STRATEGIES_PER_USER`, `MAX_EMOTIONS_PER_USER`, `MAX_WATCHLIST_KEYS`) are enforced before insert by counting the account's rows; exceeding one is a `400` ("limit reached"). `POST /api/journal/import` additionally refuses a payload whose array is not a list or holds more trades than the cap.

---

## 11. Open Spec Questions (GAPs) — user decisions only

| ID | Question | Current behavior (code) | Options | Decision (2026-11-18) |
| --- | --- | --- | --- | --- |
| GAP-1 | Should optional trade fields be clearable? | Explicit `null` now clears a field; absent keys leave it untouched | (a) keep as-is, (b) distinguish absent vs null | **(b) — implemented, SPEC-PER-5** |
| GAP-2 | Should `/api/journal/import` validate? | Raw dicts bulk-inserted; no Pydantic validation, no `html.escape`, no `BUY/SELL` normalization | (a) accept as trusted-import, (b) validate per-trade and reject/report failures | **open — awaiting decision** |
| GAP-3 | Keep the legacy `?action=&type=` compat routes? | Removed; `/api/journal` now exposes only GET | (a) keep + spec as permanent, (b) deprecate/remove | **(b) — removed, SPEC-API-8** |
| GAP-4 | Move seeding to startup? | Seeds only as a side effect of the first `GET /api/journal` | (a) keep lazy, (b) seed in lifespan startup | **open — awaiting decision** |
| GAP-5 | Add TTL/staleness handling to `price_cache`? | Entries carry a timestamp; `/api/prices` reports `meta.as_of` and `meta.stale` against `PRICE_MAX_AGE_SECONDS` | (a) accept, (b) timestamp + max-age, (c) return `null` for unknown tokens | **(b) — implemented; (c) not taken, SPEC-MKT-2 / SPEC-API-1** |
| GAP-6 | Add unique indexes for strategy/emotion names? | Regex pre-check only; concurrent adds can duplicate | (a) accept, (b) create unique indexes per owner (needs migration) | **(b) — superseded 2026-11-18: open signup makes a race-prone pre-check unacceptable; unique index on `(owner_id, name_lower)`, SPEC-AUTH-8** |
| GAP-7 | Automate Upstox token refresh? | The console's **Analytics token** (read-only, 1-year validity) is pasted into `UPSTOX_ACCESS_TOKEN`; the feed retries every 10 s on failure | (a) build an OAuth refresh flow, (b) rely on the Analytics token and renew yearly, (c) drop live prices | **(b) — closed 2026-11-18: no OAuth app or daily chore; token expiry date must be tracked, SPEC-MKT-3 / SPEC-CFG-2** |
| GAP-8 | Type the API responses? | Every endpoint declares a Pydantic `response_model`; envelope/meta models in `app/models/responses.py` | (a) leave untyped, (b) wire `response_model`s | **(b) — implemented, SPEC-MDL-6 / SPEC-API-0** |
| GAP-9 | Per-user or global watchlist? | `GET`/`PUT /api/watchlist` per account; `SubscriptionRegistry` diffs the union against the live socket each sync cycle | (a) keep one global demo list, (b) per-user watchlist + dynamic subscribe/unsubscribe on the live feed, (c) fixed NSE index basket | **(b) — implemented 2026-11-18, SPEC-AUTH-14 / SPEC-MKT-7 / SPEC-MKT-8** |
| GAP-10 | Abuse controls for open signup? | Per-`(user, ip)` sliding window on mutations (`429` + `Retry-After`) plus hard per-user caps checked before insert | (a) none, (b) per-user caps + per-IP rate limit on mutations, (c) Clerk allowlist instead of open signup | **(b) — implemented 2026-11-18, SPEC-AUTH-15 / SPEC-AUTH-16** |
| GAP-11 | What happens to documents created before v1.3 (no `owner_id`)? | Nothing to migrate: the app has never run against a live Atlas database, so no ownerless documents exist. Ownerless documents would be invisible to every account, and the partial indexes ignore them | (a) leave unclaimed, (b) one-off claim script assigning an explicit Clerk `sub`, (c) discard | **(a) — closed 2026-11-18 as not applicable: no live data yet, SPEC-AUTH-11** |

**Status: GAP-1, GAP-3, GAP-5, GAP-6, GAP-7, GAP-8, GAP-9, GAP-10, GAP-11 decided. Implemented: GAP-1/3/5/8 in v1.1, GAP-6 + GAP-7 in v1.3, the §10 auth/tenancy contract, GAP-9b and GAP-10b in v1.4. GAP-11 closed as not applicable. GAP-2 (per-trade import validation) and GAP-4 (seed at startup vs. lazily) remain open — no code change may resolve them without an explicit user decision.**

