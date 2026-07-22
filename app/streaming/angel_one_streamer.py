import time
import logging
import pyotp
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from SmartApi import SmartConnect
from app.streaming.base_streamer import IMarketDataStreamer
from app.streaming.price_cache import price_cache

logger = logging.getLogger("streamer.angel_one")

class AngelOneSmartApiStreamer(IMarketDataStreamer):
    def __init__(self, api_key: str, client_code: str, password: str, totp_secret: str):
        self.api_key = api_key
        self.client_code = client_code
        self.password = password
        self.totp_secret = totp_secret
        self.sws = None
        self.jwt_token = None
        self.feed_token = None

    def authenticate(self) -> bool:
        try:
            logger.info("Authenticating with Angel One SmartAPI...")
            smart_connect = SmartConnect(api_key=self.api_key)
            totp = pyotp.TOTP(self.totp_secret)
            totp_code = totp.now()

            response = smart_connect.generateSession(
                self.client_code, 
                self.password, 
                totp_code
            )

            if response.get("status") and "data" in response:
                session_data = response["data"]
                self.jwt_token = session_data.get("jwtToken")
                self.feed_token = session_data.get("feedToken")
                logger.info("Angel One session authentication successful.")
                return True
            else:
                logger.error(f"Angel One Handshake failed: {response.get('message')}")
                return False
        except Exception as e:
            logger.error(f"Authentication exception: {e}")
            return False

    def on_tick_received(self, token: str, ltp: float) -> None:
        price_cache.set_price(token, ltp)

    def connect_and_stream(self, tokens: list[str]) -> None:
        if not self.jwt_token and not self.authenticate():
            raise ValueError("Could not authenticate session. Stream aborted.")

        logger.info(f"Initializing Web Socket stream for tokens: {tokens}")
        self.sws = SmartWebSocketV2(
            self.jwt_token, 
            self.api_key, 
            self.client_code, 
            self.feed_token
        )

        def on_data(wsapp, message):
            if not isinstance(message, dict):
                return
            token = message.get("token")
            raw_ltp = message.get("last_traded_price")
            if raw_ltp is None:
                raw_ltp = message.get("ltp")

            if token and raw_ltp is not None:
                try:
                    ltp = float(raw_ltp) / 100.0  # Convert paise to Rupees
                    self.on_tick_received(token, ltp)
                except Exception as e:
                    logger.error(f"Error parsing price tick: {e}")

        def on_error(wsapp, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(wsapp, code, reason):
            logger.warning(f"WebSocket closed: {code} - {reason}")

        def on_open(wsapp):
            logger.info("WebSocket open. Subscribing tokens...")
            correlation_id = f"sub_{int(time.time())}"
            token_list = [{"exchangeType": 1, "tokens": tokens}]
            self.sws.subscribe(correlation_id, 1, token_list)

        self.sws.on_data = on_data
        self.sws.on_error = on_error
        self.sws.on_close = on_close
        self.sws.on_open = on_open

        self.sws.connect()
