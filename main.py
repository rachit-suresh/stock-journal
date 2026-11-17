import os
import time
import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, get_database
from app.core.indexes import ensure_indexes
from app.api.router import api_router
from app.api.endpoints import health
from app.streaming.status import mark as mark_streamer_status
from app.streaming.subscriptions import subscriptions
from app.streaming.upstox_streamer import UpstoxMarketStreamer
from app.streaming.mock_streamer import MockMarketStreamer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("server")


def start_streamer_daemon():
    """Supervise one market data connection for every signed-in account.

    The socket serves the union of all watchlists, so a second thread watches
    the subscription registry and pushes deltas into the live connection; when
    the connection dies the supervisor reconnects with the current union
    (GAP-9, SPEC-MKT-7).
    """
    subscriptions.set_defaults(settings.get_tokens())
    mock_mode = settings.MOCK_STREAMER or not settings.has_upstox_credentials()

    def build_streamer():
        if mock_mode:
            return MockMarketStreamer()
        return UpstoxMarketStreamer(access_token=settings.UPSTOX_ACCESS_TOKEN)

    def sync_subscriptions(streamer, state, stop_event):
        while not stop_event.wait(settings.STREAMER_SYNC_SECONDS):
            wanted = subscriptions.snapshot()
            if wanted == state["keys"]:
                continue
            if streamer.update_subscriptions(wanted):
                state["keys"] = wanted

    def run():
        while True:
            state = {"keys": subscriptions.snapshot()}
            stop_event = threading.Event()
            streamer = build_streamer()
            mark_streamer_status(mode="mock" if mock_mode else "upstox", connected=False)

            threading.Thread(
                target=sync_subscriptions,
                args=(streamer, state, stop_event),
                daemon=True,
            ).start()

            try:
                logger.info(f"Starting {'mock' if mock_mode else 'Upstox'} streamer with {len(state['keys'])} instruments.")
                streamer.connect_and_stream(state["keys"])

                # Some transports hand the socket to a background loop and
                # return immediately; stay attached until it reports closed.
                was_connected = False
                while not stop_event.is_set():
                    time.sleep(settings.STREAMER_SYNC_SECONDS)
                    if streamer.is_connected():
                        was_connected = True
                    elif was_connected:
                        logger.warning("Market data connection closed; reconnecting.")
                        break
            except Exception as e:
                logger.error(f"Streamer error: {e}. Retrying in 10s...")
                time.sleep(10)
            finally:
                stop_event.set()
                mark_streamer_status(connected=False)

    threading.Thread(target=run, daemon=True).start()
    logger.info("Streamer thread initialized.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_auth_config()
    if settings.auth_mode() == "dev-bypass":
        logger.warning("AUTH_DISABLED is on: every request is treated as %s.", settings.DEV_USER_ID)

    await connect_to_mongo()
    await ensure_indexes(get_database())
    start_streamer_daemon()
    yield
    await close_mongo_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    # Bearer tokens travel in a header, never in cookies, so credentialed
    # requests are unnecessary — and a wildcard origin forbids them anyway.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public liveness probe, then the authenticated API surface.
app.include_router(health.router)
app.include_router(api_router)

# Serve static frontend UI assets
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
