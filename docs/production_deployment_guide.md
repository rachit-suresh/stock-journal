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

# Upstox Credentials (Optional: Leave blank to auto-run in MOCK mode)
UPSTOX_ACCESS_TOKEN=your_upstox_oauth_access_token

# Streamer Mode (Set to true for initial deployment before obtaining a live access token)
MOCK_STREAMER=true

# Instrument Keys to Stream (NSE Equities: SBIN, PNB, TCS, INFY, WIPRO)
TOKENS=NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022
```

#### Frontend (Vercel Project Environment Variables)
```env
# FastAPI Backend Production URL
FASTAPI_BACKEND_URL=https://stock-journal-xenm.onrender.com
```

---

## 2. Pre-Deployment Verification Checklist

Before pushing to production, verify all pre-flight checks:

- [x] **Dependencies Cleaned**: `requirements.txt` contains clean production stack (`fastapi`, `uvicorn`, `motor`, `pymongo`, `upstox-python-sdk`, `websocket-client`, `pytest`, `pytest-asyncio`, `httpx`).
- [x] **Python Package Initialization**: `__init__.py` markers present in all subpackages in `app/` and `tests/`.
- [x] **Automated Test Suite**: Run `python -m pytest -v` to ensure 100% test pass rate (18/18 tests passing).
- [x] **Environment Secrets Ignored**: `.gitignore` configured to exclude `.env`, `.pytest_cache/`, `__pycache__/`, and `.venv/`.
- [x] **Vercel API Proxy Rewrites**: `vercel.json` configured with `/api/:path*` proxy rule to forward requests server-side to Render.
- [x] **CORS Security Enforced**: `CORSMiddleware` in `main.py` uses `ALLOWED_ORIGINS` setting from `app/core/config.py`.
- [x] **Database Active Ping Validation**: MongoDB connection runs `await client.admin.command('ping')` on startup to verify connectivity.
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
   Add `MONGO_URI`, `MONGO_DB_NAME`, `ALLOWED_ORIGINS`, `MOCK_STREAMER=true` (or `UPSTOX_ACCESS_TOKEN` when available).

### Render Free Tier Behavior & Keep-Alive Strategy
- **Inactivity Sleep**: Render free Web Services spin down after 15 minutes of zero HTTP traffic.
- **Trading Hours Activity**: Continuous frontend price polling (`GET /api/prices` every 2.5s) keeps the server active 100% of the time while your browser tab is open.
- **Optional 24/7 Zero-Sleep Keep-Alive**: Use a free uptime monitoring service like [UptimeRobot](https://uptimerobot.com) to ping `https://stock-journal-xenm.onrender.com/api/prices?tokens=NSE_EQ%7CINE062A01020` every 10 minutes.

---

## 4. Vercel Deployment Instructions (Static Frontend UI)

1. Connect your GitHub repository to [Vercel](https://vercel.com).
2. Click **Import** on `rachit-suresh/stock-journal`.
3. Configure Project Settings:
   - **Framework Preset**: `Other`
   - **Root Directory**: `.` (Project Root)
   - **Build Command**: *(Leave Blank / Override: None)*
   - **Output Directory**: `static`
4. Environment Variables:
   - **Key**: `FASTAPI_BACKEND_URL`
   - **Value**: `https://stock-journal-xenm.onrender.com`
5. Click **Deploy**.

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
