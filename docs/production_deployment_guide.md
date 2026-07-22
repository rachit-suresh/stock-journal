# Production Deployment & Setup Guide

This guide details everything required to configure, test, and deploy the Stock Journal monolithic application to cloud platforms (Render, Railway, Fly.io, Vercel, or VPS).

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

```env
# ==============================================================================
# DATABASE CONFIGURATION (MongoDB)
# ==============================================================================
# Local MongoDB:
MONGO_URI=mongodb://localhost:27017

# Cloud MongoDB Atlas Cluster (Recommended for Production):
# MONGO_URI=mongodb+srv://<username>:<password>@cluster0.xxx.mongodb.net/stock_journal?retryWrites=true&w=majority

MONGO_DB_NAME=stock_journal

# ==============================================================================
# BROKER MARKET DATA CONFIGURATION (Angel One SmartAPI)
# ==============================================================================
SMART_API_KEY=your_angel_one_api_key
SMART_CLIENT_CODE=your_client_code
SMART_PASSWORD=your_trading_password
SMART_TOTP_SECRET=your_2fa_totp_secret_key

# Set to true for initial deployment before obtaining live API keys
MOCK_STREAMER=true

# Instrument Tokens to Stream (NSE Equities: 3045=SBIN, 2885=PNB, 11536=TCS, 1594=INFY, 3456=WIPRO)
TOKENS=3045,2885,11536,1594,3456
```

---

## 2. Pre-Deployment Verification Checklist

Before pushing to production, verify all pre-flight checks:

- [x] **Dependencies Locked**: `requirements.txt` contains `fastapi`, `uvicorn`, `motor`, `pymongo`, `smartapi-python`, `pyotp`, `logzero`, `websocket-client`, `pytest`, `pytest-asyncio`, `httpx`.
- [x] **Automated Test Suite**: Run `python -m pytest -v` to ensure 100% test pass rate (18/18 tests passing).
- [x] **Environment Secrets Ignored**: `.gitignore` configured to exclude `.env`, `.pytest_cache/`, `__pycache__/`, and `.venv/`.
- [x] **Database Fallback Verification**: MongoDB auto-connects on lifespan startup and seeds default mock trades/strategies/emotions if database collections are empty.
- [x] **Streamer Thread Fault Isolation**: Background WebSocket streamer runs inside an isolated daemon thread, preventing event loop blocking.
- [x] **CORS & Static Assets**: Static UI assets (`static/`) mounted at `/`, allowing direct web dashboard access on port `$PORT`.

---

## 3. Render Deployment Instructions (Recommended Monolith Platform)

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
6. **Environment Variables**:
   Add `MONGO_URI`, `MONGO_DB_NAME`, `MOCK_STREAMER=true` (or live SmartAPI keys when available).

---

## 4. Running Automated Tests Locally

```bash
python -m pytest -v
```

All 18 unit and integration tests execute using isolation mocks and in-memory test repositories:
- `tests/test_models.py` (Pydantic field constraints & types)
- `tests/test_price_cache.py` (Multi-thread concurrent write safety)
- `tests/test_repositories.py` (CRUD operations & cascading category deletion updates)
- `tests/test_api_endpoints.py` (FastAPI REST endpoints & OpenAPI schema verification)
