import threading
from typing import Dict

class PriceCache:
    def __init__(self):
        self._prices: Dict[str, float] = {}
        self._lock = threading.Lock()

    def set_price(self, token: str, ltp: float):
        with self._lock:
            self._prices[token] = ltp

    def get_price(self, token: str, default: float = 100.0) -> float:
        with self._lock:
            return self._prices.get(token, default)

    def get_batch_prices(self, tokens: list[str]) -> Dict[str, float]:
        with self._lock:
            return {t: self._prices.get(t, 100.0) for t in tokens}

# Global singleton thread-safe price cache instance
price_cache = PriceCache()
