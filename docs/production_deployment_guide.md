# Production Deployment & Setup Guide

This guide details everything required to configure, test, and deploy the Stock Journal application to production cloud platforms (**Render** for the Python FastAPI Monolith Backend & Streamer, and **Vercel** for the Static UI Dashboard).

---

## 1. Environment Setup & Key Handling

### Initial Deployment Strategy (Before Having an Upstox Access Token)
When deploying the application initially to Render or Vercel, **you may not yet have an Upstox Analytics Access Token** (generated in the developer console under `My Apps → Analytics`; read-only, one-year validity, covers Market Data + Streaming — no OAuth app needed).

The application is engineered to handle this scenario out-of-the-box:
1. On initial deployment, leave `UPSTOX_ACCESS_TOKEN` empty and set `MOCK_STREAMER=true`.
2. The server will boot cleanly in **Mock Simulation Mode**, streaming realistic live price movements for the default instrument keys (SBIN, PNB, TCS, INFY, WIPRO).
3. Once you have your live Upstox access token:
   - Add `UPSTOX_ACCESS_TOKEN` to your environment variables.
   - Set `MOCK_STREAMER=false`.
   - On the next automatic deployment/restart, the server will seamlessly connect to Upstox's market data feed v3 WebSocket.

> **Note:** the Analytics Access Token is valid for one year and is **read-only** (market data, streaming; no order placement). Set a calendar reminder to rotate it before expiry — the console shows the expiry date. When it lapses or is revoked, the streamer retries every 10 s with an invalid token and mock mode is not auto-restored, but `/api/prices` keeps serving the last ticks flagged `meta.stale: true`. Treat the token as a secret: it belongs in the Render environment (or local `.env`), never in `static/` or git.

### Environment Variables Matrix

#### Backend (Render Web Service Environment Variables)
```env
# Database: Supabase Postgres. Use the **Session pooler** connection string
# (Dashboard -> Connect): the direct `db.<ref>.supabase.co` host is IPv6-only
# and Render has no IPv6 egress. Copy it verbatim - it already carries the
# password, so treat it as a secret.
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres

# CORS Security (Restrict API calls to Vercel and Localhost)
ALLOWED_ORIGINS=https://your-app.vercel.app,http://localhost:8000

# Identity (Supabase Auth). The project URL is also the JWT issuer prefix:
# tokens carry `iss = <SUPABASE_URL>/auth/v1`.
ENV=production
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon public key>
AUTH_DISABLED=false

# Only for a project whose JWT signing key is still the legacy shared secret;
# leave it unset when the project uses asymmetric (ES256/RS256) keys.
# SUPABASE_JWT_SECRET=<jwt secret>

# Upstox Credentials (Optional: Leave blank to auto-run in MOCK mode)
UPSTOX_ACCESS_TOKEN=your_upstox_analytics_access_token

# Streamer Mode (Set to true for initial deployment before obtaining a live access token)
MOCK_STREAMER=true

# Instrument Keys streamed for every account that has not saved a watchlist
TOKENS=NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022

# Abuse limits (optional overrides; these are the defaults)
MUTATION_RATE_LIMIT_PER_MINUTE=60
MAX_TRADES_PER_USER=2000
MAX_STRATEGIES_PER_USER=50
MAX_EMOTIONS_PER_USER=50
MAX_WATCHLIST_KEYS=25
WATCHLIST_TTL_SECONDS=3600
STREAMER_SYNC_SECONDS=15
```

#### Frontend (Vercel)

**No environment variables are required, and no key is stored in the HTML.** Vercel only serves `static/` as-is — there is no build step, so Vercel env vars are never injected into the pages. Instead, `static/auth.js` calls `GET /auth/config` on the backend (`vercel.json` rewrites that path, as well as `/api/*`, to the Render deployment) and receives

```json
{ "provider": "supabase", "url": "https://<ref>.supabase.co", "anonKey": "<anon public key>" }
```

Both values are public by design: the anon key only identifies the project, and Row Level Security leaves it no access to the tables. This is what keeps the switch a pure environment-variable change: Render's env decides which Supabase project the browser talks to.

| Constant in `static/index.html` | Purpose | Default |
| --- | --- | --- |
| `window.FASTAPI_BACKEND_URL` | Origin of the FastAPI service `apiFetch` calls | same origin on `localhost`/`127.0.0.1`; `https://stock-journal-xenm.onrender.com` elsewhere |

Serving from the same origin is correct in both deployments (Render serves the page itself, and `vercel.json` rewrites `/api/*` to Render). The absolute default only matters when the page is opened from a plain static file server.

### Supabase Setup (one-time, ~10 minutes)
1. Create a project at [supabase.com](https://supabase.com) (any region near you; note the `<ref>` in its URL).
2. **Authentication -> Providers -> Email**: keep *Enable email provider* on. Turn **Confirm email** *off* — the app has no mail flow, and with confirmation on a new account cannot sign in until the link is clicked. (The UI does handle that case: it tells the user to confirm, then sign in.)
3. **Authentication -> URL Configuration**: set *Site URL* and add *Redirect URLs* for `https://<your-app>.vercel.app` and `http://localhost:8000`. Only needed if you later add OAuth or magic links; password sign-in works without it.
4. **Project Settings -> API**: copy the *Project URL* into `SUPABASE_URL` and the *anon public* key into `SUPABASE_ANON_KEY` on Render. Do not use the `service_role` key anywhere — it bypasses RLS.
5. **Project Settings -> API -> JWT Settings**: if the project still signs with HS256, copy the *JWT Secret* into `SUPABASE_JWT_SECRET`. Projects created on the new asymmetric keys publish a JWKS instead, which the backend fetches from `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`; nothing else is needed.
6. **Database -> Connect**: copy the **Session pooler** URI into `DATABASE_URL` on Render.
7. Nothing else: the tables and indexes are created by the app on boot, with RLS enabled on all four (`app/core/schema.py`, idempotent).

> **Why RLS matters here.** Supabase exposes every `public` table over its REST API to anyone holding the anon key, and that key is in the page. The schema enables Row Level Security on all four tables and defines **no policies**, so the anon and authenticated PostgREST roles can read and write nothing. The backend connects as the table owner (the pooler user), which is not subject to RLS. If you ever add a policy, you are opening that door deliberately.

### Migrating away from MongoDB / Clerk

This release removes both: `motor` and `pymongo` are gone from `requirements.txt`, and the `app/repositories/mongo/` package and `app/core/indexes.py` are deleted. There is **no data migration**: the app has never held real user data, and each account re-seeds the demo journal on its first `GET /api/journal`. Delete the old `MONGO_URI`, `MONGO_DB_NAME` and `CLERK_ISSUER` variables from Render after the deploy succeeds; leaving them set is harmless but misleading.

---

## 2. Pre-Deployment Verification Checklist

Before pushing to production, verify all pre-flight checks:

- [x] **Dependencies Cleaned**: `requirements.txt` contains the production stack only (`fastapi`, `uvicorn`, `asyncpg`, `upstox-python-sdk`, `websocket-client`, `PyJWT[crypto]`, `pytest`, `pytest-asyncio`, `httpx`). `motor` and `pymongo` are gone, and `pgserver` lives in `requirements-dev.txt` because Render's default Python is newer than the package's wheels.
- [x] **Python Package Initialization**: `__init__.py` markers present in all subpackages in `app/` and `tests/`.
- [x] **Automated Test Suite**: `python -m pytest -q` → **78 passed** (auth, tenancy, caps, watchlist, streaming, repositories, API, plus 14 Postgres integration tests against a real server).
- [x] **Environment Secrets Ignored**: `.gitignore` excludes `.env`, `.pytest_cache/`, `__pycache__/`, `.venv/` and the throwaway `.pgtest/` cluster.
- [x] **Vercel API Proxy Rewrites**: `vercel.json` rewrites `/api/:path*` **and** `/auth/config` to Render, so the browser never needs a cross-origin call.
- [x] **CORS Security Enforced**: `CORSMiddleware` in `main.py` uses `ALLOWED_ORIGINS` with `allow_credentials=False`.
- [x] **Auth Fail-Closed**: `ENV=production` + `AUTH_DISABLED=true` aborts startup; a missing `SUPABASE_URL` answers `401` instead of opening the API.
- [x] **Database Reachability Probe**: the pool is opened on startup and `GET /health` runs `SELECT 1` per request (`database: ok|unavailable`). A failed connect logs and leaves the process serving `503` on data routes, so `/health` can report the cause.
- [x] **Schema Bootstrap**: `ensure_schema()` creates the four tables, their indexes and RLS under an advisory lock on boot (idempotent).
- [x] **Server-Side Input Sanitization**: Pydantic models sanitize ticker symbols, validate trade sides, and HTML-escape user notes and categories.
- [x] **Streamer Thread Fault Isolation**: Background WebSocket streamer runs inside an isolated daemon thread, preventing event loop blocking.

---

## 3. Render Deployment Instructions (Backend & Streamer)

1. Connect your GitHub repository to [Render](https://render.com).
2. Create a new **Web Service**.
3. **Environment**: Python 3.10+
4. **Build Command**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Start Command**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
   *(Note: Render automatically injects `$PORT` behind the scenes).*
6. **Environment Variables**:
   Add `DATABASE_URL` (Supabase session pooler URI), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `ALLOWED_ORIGINS`, `ENV=production`, `AUTH_DISABLED=false`, and either `MOCK_STREAMER=true` or `UPSTOX_ACCESS_TOKEN`. Add `SUPABASE_JWT_SECRET` only if the project signs tokens with HS256.
7. **Health Check Path**: `/health` (public; returns auth mode + streamer state).

### Render Free Tier Behavior & Keep-Alive Strategy
- **Inactivity Sleep**: Render free Web Services spin down after 15 minutes of zero HTTP traffic.
- **Trading Hours Activity**: Continuous frontend price polling (`GET /api/prices` every 2.5s) keeps the server active 100% of the time while your browser tab is open.
- **Optional 24/7 Zero-Sleep Keep-Alive**: Use a free uptime monitoring service like [UptimeRobot](https://uptimerobot.com) to ping `https://stock-journal-xenm.onrender.com/health` every 10 minutes (public, so no token is needed — `/api/prices` now requires authentication and would answer `401`).
- **Counters reset on spin-down**: the rate-limit buckets and the watchlist registry are in memory, so a sleeping instance forgets them. Clients repopulate the registry on their next `GET /api/watchlist`, and the limiter simply starts a fresh window.

---

## 4. Vercel Deployment Instructions (Static Frontend UI)

1. Connect your GitHub repository to [Vercel](https://vercel.com).
2. Click **Import** on `rachit-suresh/stock-journal`.
3. Configure Project Settings:
   - **Framework Preset**: `Other`
   - **Root Directory**: `.` (Project Root)
   - **Build Command**: *(Leave Blank / Override: None)*
   - **Output Directory**: `static`
4. Environment Variables: **none** — the static site reads its backend URL from `static/index.html` and its Supabase URL / anon key from `GET /auth/config`, not from Vercel env vars (there is no build step to inject them).
5. Only edit `static/index.html` if your Render service is not `stock-journal-xenm.onrender.com` (and update `vercel.json` too). Commit → Vercel redeploys.
6. Click **Deploy**.

> The static site is served from `static/`, so every UI change ships with a Vercel deploy. Bump the `?v=` query strings in `index.html` when you change CSS/JS to defeat browser caching.

---

## 5. Troubleshooting & Common Deployment Pitfalls

### Issue 1: `ConnectionRefusedError` / `getaddrinfo failed` / `password authentication failed`
- **Symptom**: Render logs show `Failed to connect to Postgres: ...` and every data route answers `503`; `/health` reports `"database": "unavailable"`.
- **Cause** (in order of likelihood):
  1. `DATABASE_URL` uses the **direct** host `db.<ref>.supabase.co`. That host resolves to IPv6 only, and Render has no IPv6 egress. Use the **Session pooler** URI from Dashboard → Connect instead.
  2. The password was not re-copied after a reset, or the `[YOUR-PASSWORD]` placeholder is still in the string.
  3. The connection string is missing its scheme (`postgresql://`) because the dashboard URL was pasted instead of the connection string.
  4. The password contains a reserved character that was never encoded - see Issue 1c.
- **Verify**: `/health` → `database`; then `psql "$DATABASE_URL" -c 'select 1'` from any machine that can reach Supabase. Note that the pooler also requires the pooler username form `postgres.<ref>` — the plain `postgres` user only exists on the direct host.

### Issue 1b: `prepared statement "__asyncpg_stmt_…" does not exist`
- **Cause**: server-side prepared statements do not survive a transaction pooler.
- **Fix**: already handled — the pool is created with `statement_cache_size=0`. Do not remove that argument, and prefer the **session** pooler URI for the same reason.

### Issue 1c: `bad query field: '<tail of your password>@aws-1-….pooler.supabase.com:5432/postgres'`
- **Symptom**: Render logs show `Failed to connect to Postgres: bad query field: ...` and `/health` stays at `"database": "unavailable"`. The host in the message is real and correct, which sends you looking in the wrong place.
- **Cause**: a reserved character in the **password**. `?` ends the authority and starts the query string, so `user:password` becomes the netloc and the host plus port become a bogus query field; `#` does the same to the fragment. Render stores the value verbatim, so `asyncpg` never sees a host at all.
- **Fix**: percent-encode the password and paste the encoded form — `?`→`%3F`, `#`→`%23`, `%`→`%25`, `@`→`%40`, `/`→`%2F`, `:`→`%3A`. To produce it locally:
  ```bash
  python -c "from urllib.parse import quote; print(quote('<raw password>', safe=''))"
  ```
  Alternatively reset the database password (Dashboard → Settings → Database) to an alphanumeric-only value, which needs no encoding and survives future copy-paste.
- **Note**: `connect_to_database()` checks the URI before talking to Postgres and logs `DATABASE_URL is unusable, a reserved character in the password …` instead of the misleading `asyncpg` error.

### Issue 2: Vercel Rewrites for Backend Proxying
- **Symptom**: Frontend fetch requests to `/api/...` receive 404 HTML responses on Vercel.
- **Cause**: Vercel static router treating `/api/` as a static folder path.
- **Fix**: Ensure `vercel.json` includes the backend proxy rewrite rule:
  ```json
  {
    "cleanUrls": true,
    "rewrites": [
      {
        "source": "/api/:path*",
        "destination": "https://stock-journal-xenm.onrender.com/api/:path*"
      },
      {
        "source": "/(.*)",
        "destination": "/static/$1"
      }
    ]
  }
  ```

### Issue 3: CORS Blocking Frontend AJAX Requests
- **Symptom**: Browser console displays `Access to fetch at ... from origin ... has been blocked by CORS policy`.
- **Cause**: Render backend CORS configuration does not include your Vercel domain.
- **Fix**: Set `ALLOWED_ORIGINS` in Render Environment Variables:
  ```env
  ALLOWED_ORIGINS=https://your-app.vercel.app,http://localhost:8000
  ```

### Issue 4: Every API Call Returns `401`
- **Symptom**: the UI shows the sign-in gate, or the note reads `Invalid or expired session token`; `/health` reports `"auth": "supabase"` but requests fail.
- **Cause** (in order of likelihood):
  1. `SUPABASE_URL` missing or pointing at a different project than the one the browser signed into (`iss` mismatch — the claim must equal `<SUPABASE_URL>/auth/v1`).
  2. `/auth/config` returns `{"provider":"none"}` → the backend runs with `AUTH_DISABLED=true`, so the UI opens in dev mode and sends no token; the API then rejects nothing but the sidebar reads "Dev mode".
  3. **Confirm email** is still on in Supabase: new accounts exist but never receive a session. Turn it off.
  4. A legacy HS256 project without `SUPABASE_JWT_SECRET`: the token's `alg` is `HS256`, and the backend refuses to verify it without the secret (it never falls back to JWKS, to avoid algorithm confusion).
- **Verify**: `curl https://<render-host>/health` must return `"auth": "supabase"` and `"database": "ok"`; then `curl -i https://<render-host>/api/journal` must return `401` with a JSON detail. `GET /auth/config` must return the project URL, not `{"provider":"none"}`. To inspect a token, paste it into [jwt.io](https://jwt.io) and check `iss`, `aud: authenticated`, `exp` and `sub` (a UUID).
- **Local dev**: set `AUTH_DISABLED=true` to skip Supabase entirely (the gate then opens straight into the app as `dev-local`).

### Issue 5: Signed In, But The Journal Is Empty After A Refresh
- **Cause**: you are signed in with a different account than the one that created the data, or `AUTH_DISABLED` was flipped without clearing `localStorage` (dev bypass uses the fixed `dev-local` subject).
- **Fix**: check `/health` → `auth`, and the sidebar account row (the Supabase user email). Sign out and back in — sign-out clears `stock_journal_*` keys by design. Accounts are keyed by the JWT `sub`, so signing up twice with the same address does not merge data.

### Issue 6: Watchlist Instrument Never Shows A Price
- **Cause**: the streamer had not yet re-synced when you looked (up to `STREAMER_SYNC_SECONDS`), the key format is wrong (`NSE_EQ|INE002A01018`), or the Upstox token lacks that segment.
- **Verify**: `GET /health` → `streamer.connected`; `GET /api/prices?tokens=<your key>` should return a value that stops changing if the feed is dead (`meta.stale: true`).

