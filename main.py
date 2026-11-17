import os
import sys
import time
import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.api.router import api_router
from app.streaming.upstox_streamer import UpstoxMarketStreamer
from app.streaming.mock_streamer import MockMarketStreamer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("server")

def start_streamer_daemon():
    tokens = settings.get_tokens()
    mock_mode = settings.MOCK_STREAMER or not settings.has_upstox_credentials()
    
    def run():
        while True:
            try:
                if mock_mode:
                    logger.info("Starting Mock Market Streamer daemon...")
                    streamer = MockMarketStreamer()
                else:
                    logger.info("Starting Upstox Market Data Streamer daemon...")
                    streamer = UpstoxMarketStreamer(
                        access_token=settings.UPSTOX_ACCESS_TOKEN
                    )
                streamer.connect_and_stream(tokens)
            except Exception as e:
                logger.error(f"Streamer error: {e}. Retrying in 10s...")
                time.sleep(10)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.info("Streamer thread initialized.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect MongoDB
    await connect_to_mongo()
    # Start streamer thread
    start_streamer_daemon()
    yield
    # Shutdown
    await close_mongo_connection()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API endpoints
app.include_router(api_router)

# Serve static frontend UI assets
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
