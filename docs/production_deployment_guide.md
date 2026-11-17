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
# Database Settings (MongoDB Atlas Cloud Cluster)
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.xxx.mongodb.net/stock_journal?retryWrites=true&w=majority
MONGO_DB_NAME=stock_journal

# CORS Security (Restrict API calls to Vercel and Localhost)
ALLOWED_ORIGINS=https://your-app.vercel.app,http://localhost:8000

# Identity (Clerk) — the issuer URL shown in Clerk → API keys / JWT verification
ENV=production
CLERK_ISSUER=https://<instance>.clerk.accounts.dev
AUTH_DISABLED=false

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

**No environment variables are required.** Vercel only serves `static/` as-is — there is no build step, so Vercel env vars are never injected into the HTML and setting `FASTAPI_BACKEND_URL` there has no effect. Both frontend values live in `static/index.html`:

| Constant in `static/index.html` | Purpose | Example |
| --- | --- | --- |
| `window.FASTAPI_BACKEND_URL` (line ~9) | Origin of the FastAPI service that `apiFetch` calls | `https://stock-journal-xenm.onrender.com` |
| `window.CLERK_PUBLISHABLE_KEY` (line ~13) | Clerk instance (public by design) | `pk_test_…` |

The Render host also appears in `vercel.json` as the `/api/:path*` rewrite destination; keep the two in sync if you rename the service. Leaving `CLERK_PUBLISHABLE_KEY` empty keeps the UI in dev mode (the sidebar then reads "Dev mode"), which fails against a production API that requires a token.

### Clerk Setup (one-time, ~5 minutes)
1. Create an application at [dashboard.clerk.com](https://dashboard.clerk.com) (name it e.g. `stock-journal`).
2. **Stay on the Development instance.** Do not promote a Production instance unless you own a real domain — see the warning below.
3. **User & Authentication → Email, phone, username**: enable **Email address** and add **Google** as a social connection.
4. **Configure → Restrictions**: keep sign-up open (the app is designed for open signup), and leave "Require email verification" on.
5. **Configure → Paths**: leave the hosted pages enabled, or set `Sign-in URL` / `Sign-up URL` to your Vercel domain if you prefer the hosted flow.
6. **API keys**:
   - Copy the **Publishable key** (`pk_test_…`) into `static/index.html` → `window.CLERK_PUBLISHABLE_KEY`.
   - Copy the **Issuer** (`https://<slug>.clerk.accounts.dev`) into Render as `CLERK_ISSUER`. It is also the `iss` claim in the JWKS, so a mismatch means every token is rejected with `401`.
   - Ignore the `CLERK_SECRET_KEY` / `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` snippet: this is a static frontend, the secret key is never used (tokens are verified against the public JWKS).
7. **Configure → Domains / Allowed origins**: add `https://<your-app>.vercel.app` (and `http://localhost:8000` while testing). Clerk refuses to mint sessions for unlisted origins.

> **A Clerk Production instance cannot run on `*.vercel.app`.** Its Frontend API lives on `clerk.<primary-domain>`, and Vercel's wildcard certificate `*.vercel.app` covers only one label, so `clerk.<project>.vercel.app` fails the TLS handshake (Clerk's dashboard shows the domain as **Pending** forever, and no CNAME can be created in a zone you do not control). With that key, `clerk.browser.js` never loads and the backend's JWKS fetch fails, so every `/api` call answers `401`. Either stay on the Development instance (recommended for a two-person app) or attach a real, owned domain to Vercel before promoting to Production. Recorded in `design_decisions_and_tradeoffs.md` §11.

---

## 2. Pre-Deployment Verification Checklist

Before pushing to production, verify all pre-flight checks:

- [x] **Dependencies Cleaned**: `requirements.txt` contains the production stack (`fastapi`, `uvicorn`, `motor`, `pymongo`, `upstox-python-sdk`, `websocket-client`, `PyJWT[crypto]`, `pytest`, `pytest-asyncio`, `httpx`).
- [x] **Python Package Initialization**: `__init__.py` markers present in all subpackages in `app/` and `tests/`.
- [x] **Automated Test Suite**: `python -m pytest -q` → **56 passed** (auth, tenancy, caps, watchlist, streaming, repositories, API).
- [x] **Environment Secrets Ignored**: `.gitignore` configured to exclude `.env`, `.pytest_cache/`, `__pycache__/`, and `.venv/`.
- [x] **Vercel API Proxy Rewrites**: `vercel.json` configured with `/api/:path*` proxy rule to forward requests server-side to Render.
- [x] **CORS Security Enforced**: `CORSMiddleware` in `main.py` uses `ALLOWED_ORIGINS` with `allow_credentials=False`.
- [x] **Auth Fail-Closed**: `ENV=production` + `AUTH_DISABLED=true` aborts startup; a missing `CLERK_ISSUER` answers `401` instead of opening the API.
- [x] **Database Active Ping Validation**: MongoDB connection runs `await client.admin.command('ping')` on startup to verify connectivity.
- [x] **Owner Indexes Created**: `ensure_indexes()` builds the partial unique indexes on startup (failures are logged, not fatal).
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
   Add `MONGO_URI`, `MONGO_DB_NAME`, `ALLOWED_ORIGINS`, `ENV=production`, `CLERK_ISSUER`, `AUTH_DISABLED=false`, and either `MOCK_STREAMER=true` or `UPSTOX_ACCESS_TOKEN`.
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
4. Environment Variables: **none** — the static site reads its backend URL and Clerk key from `static/index.html`, not from Vercel env vars (there is no build step to inject them).
5. Edit `static/index.html` and set `window.CLERK_PUBLISHABLE_KEY = "pk_test_…";` (the empty default is dev mode), plus `window.FASTAPI_BACKEND_URL` if your Render service is not `stock-journal-xenm.onrender.com`. Commit → Vercel redeploys.
6. Click **Deploy**.

> The static site is served from `static/`, so every UI change ships with a Vercel deploy. Bump the `?v=` query strings in `index.html` when you change CSS/JS to defeat browser caching.

---

## 5. Troubleshooting & Common Deployment Pitfalls

### Issue 1: `ServerSelectionTimeoutError` / MongoDB Connection Failure
- **Symptom**: Render server logs show `ServerSelectionTimeoutError: No servers found yet`.
- **Cause**: MongoDB Atlas Network Access IP Whitelist is blocking outbound connections from Render.
- **Fix**:
  1. Log into [MongoDB Atlas](https://www.mongodb.com/cloud/atlas).
  2. Navigate to **Network Access** $\rightarrow$ Click **Add IP Address**.
  3. Enter `0.0.0.0/0` (Allow Access From Anywhere) and confirm.

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
- **Symptom**: the UI shows the sign-in gate, or `Sign-in is unavailable right now`; `/health` reports `"auth": "clerk"` but requests fail.
- **Cause** (in order of likelihood):
  1. `CLERK_ISSUER` missing or not the issuer of the key in `index.html` (two different Clerk instances, or the `…clerk.accounts.dev` host copied from another project).
  2. The publishable key in `index.html` still empty → the UI runs in dev mode and sends no token.
  3. The Vercel origin is missing from Clerk's allowed origins, so no session can be minted.
  4. A stale token: the UI signs out and reloads automatically; if it loops, check the browser console for the Clerk error.
- **Verify**: `curl https://<render-host>/health` must return `"auth": "clerk"`; then `curl -i https://<render-host>/api/journal` must return `401` with a JSON detail. A `500` with "AUTH_DISABLED is not allowed when ENV=production" means the env var is still `true`.
- **Local dev**: set `AUTH_DISABLED=true` and leave `CLERK_PUBLISHABLE_KEY` empty to skip Clerk entirely.

### Issue 5: Signed In, But The Journal Is Empty After A Refresh
- **Cause**: you are signed in with a different account than the one that created the data, or `AUTH_DISABLED` was flipped without clearing `localStorage` (dev bypass uses the fixed `dev-local` subject).
- **Fix**: check `/health` → `auth`, and the sidebar account row (the Clerk email). Sign out and back in — sign-out clears `stock_journal_*` keys by design.

### Issue 6: Watchlist Instrument Never Shows A Price
- **Cause**: the streamer had not yet re-synced when you looked (up to `STREAMER_SYNC_SECONDS`), the key format is wrong (`NSE_EQ|INE002A01018`), or the Upstox token lacks that segment.
- **Verify**: `GET /health` → `streamer.connected`; `GET /api/prices?tokens=<your key>` should return a value that stops changing if the feed is dead (`meta.stale: true`).

