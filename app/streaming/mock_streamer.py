import time
import random
import logging
from app.streaming.base_streamer import IMarketDataStreamer
from app.streaming.price_cache import price_cache

logger = logging.getLogger("streamer.mock")

class MockMarketStreamer(IMarketDataStreamer):
    def __init__(self):
        self.running = False
        self.prices = {
            "3045": 650.00,   # SBIN
            "2885": 80.00,    # PNB
            "11536": 3500.00, # TCS
            "1594": 1500.00,  # INFY
            "3456": 450.00,   # WIPRO
        }

    def authenticate(self) -> bool:
        logger.info("[MOCK] Authenticating mock market streamer...")
        return True

    def on_tick_received(self, token: str, ltp: float) -> None:
        price_cache.set_price(token, ltp)

    def connect_and_stream(self, tokens: list[str]) -> None:
        logger.info(f"[MOCK] Starting mock streamer for tokens {tokens}")
        self.running = True
        
        for token in tokens:
            initial = self.prices.get(token, 100.0)
            self.on_tick_received(token, initial)

        while self.running:
            time.sleep(2)
            active_tokens = [t for t in tokens if t in self.prices]
            if not active_tokens:
                active_tokens = tokens
                
            for token in random.sample(active_tokens, k=min(len(active_tokens), 2)):
                current = self.prices.get(token, 100.0)
                change = (random.random() * 0.8 - 0.4) / 100
                new_price = max(0.01, round(current * (1 + change), 2))
                self.prices[token] = new_price
                self.on_tick_received(token, new_price)
