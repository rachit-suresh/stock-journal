import logging
from app.streaming.base_streamer import IMarketDataStreamer
from app.streaming.price_cache import price_cache

logger = logging.getLogger("streamer.upstox")

class UpstoxMarketStreamer(IMarketDataStreamer):
    """Market data streamer backed by the Upstox market data feed v3.

    Auth is the account-level Analytics Access Token: read-only, valid for one
    year, accepted by the Market Data and Streaming APIs. There is no
    programmatic login, so `authenticate()` only validates token presence and
    the real handshake happens when the WebSocket connects.
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.streamer = None

    def authenticate(self) -> bool:
        return bool(self.access_token)

    def on_tick_received(self, token: str, ltp: float) -> None:
        price_cache.set_price(token, ltp)

    @staticmethod
    def _extract_ltp(feed: dict) -> float | None:
        """Pull the LTP out of a decoded feed regardless of subscription mode."""
        ltpc = feed.get("ltpc")
        if not ltpc:
            full_feed = feed.get("fullFeed") or {}
            ltpc = (full_feed.get("marketFF") or full_feed.get("indexFF") or {}).get("ltpc")
        if not ltpc:
            ltpc = (feed.get("firstLevelWithGreeks") or {}).get("ltpc")
        ltp = (ltpc or {}).get("ltp")
        return float(ltp) if ltp is not None else None

    def on_message_received(self, message) -> None:
        # Decoded v3 feed: {"type": "live_feed", "feeds": {"<instrument_key>": {...}}}
        # market_info/status messages carry no feeds and are ignored.
        if not isinstance(message, dict):
            return
        feeds = message.get("feeds")
        if not isinstance(feeds, dict):
            return
        for token, feed in feeds.items():
            try:
                ltp = self._extract_ltp(feed or {})
                if ltp is not None:
                    self.on_tick_received(token, ltp)
            except Exception as e:
                logger.error(f"Error parsing price tick for {token}: {e}")

    def connect_and_stream(self, tokens: list[str]) -> None:
        if not self.authenticate():
            raise ValueError("Upstox access token is missing. Stream aborted.")

        # Imported lazily so mock mode still runs without the SDK installed.
        import upstox_client

        logger.info(f"Connecting to Upstox market data feed for instruments: {tokens}")
        configuration = upstox_client.Configuration()
        configuration.access_token = self.access_token
        api_client = upstox_client.ApiClient(configuration)

        self.streamer = upstox_client.MarketDataStreamerV3(api_client)

        def on_open():
            logger.info("Upstox WebSocket open. Subscribing instruments...")
            # Default mode is "ltpc" (LTP + close price); decoded feed only.
            self.streamer.subscribe(tokens, "ltpc")

        def on_message(message):
            self.on_message_received(message)

        def on_error(error):
            logger.error(f"Upstox WebSocket error: {error}")

        def on_close(*args):
            logger.warning(f"Upstox WebSocket closed: {args}")

        self.streamer.on("open", on_open)
        self.streamer.on("message", on_message)
        self.streamer.on("error", on_error)
        self.streamer.on("close", on_close)

        self.streamer.connect()
