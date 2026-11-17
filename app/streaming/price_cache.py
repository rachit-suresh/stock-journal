import threading
import time
from typing import Dict, Optional, Tuple

from app.core.config import settings

# Fallback served for tokens that were never seen. Kept for backward
# compatibility with the frontend, which always expects a number.
UNKNOWN_PRICE_DEFAULT = 100.0


class PriceCache:
    """Thread-safe store of the latest LTP per Upstox instrument key.

    Writers are streamer daemon threads, readers are request handlers on the
    asyncio loop, so every access goes through a plain threading.Lock. Each
    entry keeps the wall-clock time it was written so the API can report
    staleness instead of silently serving a dead feed.
    """

    def __init__(self, max_age_seconds: Optional[float] = None):
        self._entries: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()
        self.max_age_seconds = (
            settings.PRICE_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
        )

    def set_price(self, token: str, ltp: float):
        with self._lock:
            self._entries[token] = (float(ltp), time.time())

    def get_price(self, token: str, default: float = UNKNOWN_PRICE_DEFAULT) -> float:
        with self._lock:
            entry = self._entries.get(token)
        return entry[0] if entry else default

    def get_batch_prices(self, tokens: list[str]) -> Dict[str, float]:
        with self._lock:
            snapshot = dict(self._entries)
        return {t: snapshot[t][0] if t in snapshot else UNKNOWN_PRICE_DEFAULT for t in tokens}

    def get_batch_meta(self, tokens: list[str]) -> Dict[str, dict]:
        """Per-token freshness: `as_of` (epoch ms) and `stale` (bool)."""
        now = time.time()
        with self._lock:
            snapshot = dict(self._entries)
        meta: Dict[str, dict] = {}
        for token in tokens:
            entry = snapshot.get(token)
            if entry is None:
                meta[token] = {"as_of": None, "stale": True}
            else:
                ltp_ts = entry[1]
                meta[token] = {
                    "as_of": int(ltp_ts * 1000),
                    "stale": (now - ltp_ts) > self.max_age_seconds,
                }
        return meta

    def has_fresh_data(self) -> bool:
        """True when at least one cached tick is newer than the freshness window."""
        now = time.time()
        with self._lock:
            timestamps = [ts for _, ts in self._entries.values()]
        return any((now - ts) <= self.max_age_seconds for ts in timestamps)

# Global singleton thread-safe price cache instance
price_cache = PriceCache()
