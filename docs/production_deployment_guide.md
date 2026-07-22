# Production Deployment & Setup Guide

This guide details everything required to configure, test, and deploy the Stock Journal application to production cloud platforms (**Render** for the Python FastAPI Monolith Backend & Streamer, and **Vercel** for the Static UI Dashboard).

---

## 1. Environment Setup & Key Handling

### Initial Deployment Strategy (Before Having SmartAPI Credentials)
When deploying the application initially to Render or Vercel, **you may not yet have live Angel One SmartAPI credentials** (since API keys are granted after submitting your hosted domain URL).

The application is engineered to handle this scenario out-of-the-box:
1. On initial deployment, leave `SMART_API_KEY`, `SMART_CLIENT_CODE`, `SMART_PASSWORD`, and `SMART_TOTP_SECRET` empty and set `MOCK_STREAMER=true`.
2. The server will boot cleanly in **Mock Simulation Mode**, streaming realistic live price movements for stock tokens (`3045`, `2885`, `11536`, `1594`, `3456`).
3. Once your cloud deployment URL is active and you receive your live SmartAPI key from Angel One:
   - Add your live credentials (`SMART_API_KEY`, `SMART_CLIENT_CODE`, `SMART_PASSWORD`, `SMART_TOTP_SECRET`) to your environment variables.
   - Set `MOCK_STREAMER=false`.
   - On the next automatic deployment/restart, the server will seamlessly connect to Angel One's production WebSocket feed (`wss://smartapisocket.angelone.in/smart-stream`).

### Environment Variables Matrix

#### Backend (Render Web Service Environment Variables)
```env
# Database Settings (MongoDB Atlas Cloud Cluster)
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.xxx.mongodb.net/stock_journal?retryWrites=true&w=majority
MONGO_DB_NAME=stock_journal

# CORS Security (Restrict API calls to Vercel and Localhost)
ALLOWED_ORIGINS=https://your-app.vercel.app,http://localhost:8000

# Angel One SmartAPI Credentials (Optional: Leave blank to auto-run in MOCK mode)
SMART_API_KEY=your_angel_one_api_key
SMART_CLIENT_CODE=your_client_code
SMART_PASSWORD=your_trading_password
SMART_TOTP_SECRET=your_2fa_totp_secret_key

# Streamer Mode (Set to true for initial deployment before obtaining live API keys)
MOCK_STREAMER=true

# Instrument Tokens to Stream (NSE Equities: 3045=SBIN, 2885=PNB, 11536=TCS, 1594=INFY, 3456=WIPRO)
TOKENS=3045,2885,11536,1594,3456
```

#### Frontend (Vercel Project Environment Variables)
```env
# FastAPI Backend Production URL
FASTAPI_BACKEND_URL=https://your-stock-journal.onrender.com
```

---

## 2. Pre-Deployment Verification Checklist

Before pushing to production, verify all pre-flight checks:

- [x] **Dependencies Locked**: `requirements.txt` contains `fastapi`, `uvicorn`, `motor`, `pymongo`, `smartapi-python`, `pyotp`, `logzero`, `websocket-client`, `pytest`, `pytest-asyncio`, `httpx`.
- [x] **Automated Test Suite**: Run `python -m pytest -v` to ensure 100% test pass rate (18/18 tests passing).
- [x] **Environment Secrets Ignored**: `.gitignore` configured to exclude `.env`, `.pytest_cache/`, `__pycache__/`, and `.venv/`.
- [x] **Vercel Schema Compliance**: `vercel.json` strictly adheres to Vercel v2 schema rules (no invalid `"public"` root property).
- [x] **CORS Security Enforced**: `CORSMiddleware` in `main.py` uses `ALLOWED_ORIGINS` setting from `app/core/config.py`.
- [x] **Dynamic Base URL Resolution**: Frontend (`static/state.js`, `static/mockApi.js`, `static/index.html`) automatically resolves `FASTAPI_BACKEND_URL`.
- [x] **Database Fallback Verification**: MongoDB auto-connects on lifespan startup and seeds default mock trades/strategies/emotions if database collections are empty.
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
   Add `MONGO_URI`, `MONGO_DB_NAME`, `ALLOWED_ORIGINS`, `MOCK_STREAMER=true` (or live SmartAPI keys when available).

### Render Free Tier Behavior & Keep-Alive Strategy
- **Inactivity Sleep**: Render free Web Services spin down after 15 minutes of zero HTTP traffic.
- **Trading Hours Activity**: Continuous frontend price polling (`GET /api/prices` every 2.5s) keeps the server active 100% of the time while your browser tab is open.
- **Optional 24/7 Zero-Sleep Keep-Alive**: Use a free uptime monitoring service like [UptimeRobot](https://uptimerobot.com) to ping `https://your-app.onrender.com/api/prices?tokens=3045` every 10 minutes.

---

## 4. Vercel Deployment Instructions (Static Frontend UI)

1. Connect your GitHub repository to [Vercel](https://vercel.com).
2. Click **Import** on `rachit-suresh/stock-journal`.
3. Configure Project Settings:
   - **Framework Preset**: `Other`
   - **Root Directory**: `static`
   - **Build Command**: *(Leave Blank / Override: None)*
   - **Output Directory**: *(Leave Blank / Override: None)*
4. Environment Variables:
   - **Key**: `FASTAPI_BACKEND_URL`
   - **Value**: `https://your-stock-journal.onrender.com`
5. Click **Deploy**.
