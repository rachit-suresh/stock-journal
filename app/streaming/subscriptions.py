"""Which instrument keys should be on the wire right now (GAP-9).

One Upstox socket serves every account, so the streamer needs the union of
all live watchlists. Request handlers cannot reach the socket, so they publish
their keys into this registry and the supervisor thread applies the delta
between what is subscribed and what the registry now wants.

Entries expire on their own: a browser tab that stops polling for an hour
must not keep its instruments pinned to the feed forever.
"""

import threading
import time
from typing import Dict, Iterable, List, Tuple


def diff_subscriptions(current: Iterable[str], wanted: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Return `(to_subscribe, to_unsubscribe)` between two key sets."""
    current_set = set(current)
    wanted_set = set(wanted)
    return sorted(wanted_set - current_set), sorted(current_set - wanted_set)


class SubscriptionRegistry:
    def __init__(self, defaults: Iterable[str] | None = None, ttl_seconds: float = 3600):
        self._lock = threading.Lock()
        self._defaults: List[str] = self._clean(defaults)
        self._users: Dict[str, Tuple[Tuple[str, ...], float]] = {}
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _clean(keys: Iterable[str] | None) -> List[str]:
        return sorted({k.strip() for k in (keys or []) if k and k.strip()})

    def set_defaults(self, keys: Iterable[str]) -> None:
        """The always-on basket (settings.TOKENS)."""
        with self._lock:
            self._defaults = self._clean(keys)

    def set_user_keys(self, user_id: str, keys: Iterable[str]) -> None:
        with self._lock:
            self._users[user_id] = (tuple(self._clean(keys)), time.monotonic())

    def touch_user(self, user_id: str) -> None:
        """Refresh the expiry clock without changing the key set."""
        with self._lock:
            entry = self._users.get(user_id)
            if entry:
                self._users[user_id] = (entry[0], time.monotonic())

    def drop_user(self, user_id: str) -> None:
        with self._lock:
            self._users.pop(user_id, None)

    def snapshot(self) -> List[str]:
        """Union of defaults and every non-expired user watchlist."""
        now = time.monotonic()
        with self._lock:
            if self._ttl_seconds > 0:
                for user_id, (_, last_seen) in list(self._users.items()):
                    if now - last_seen > self._ttl_seconds:
                        self._users.pop(user_id, None)

            merged = set(self._defaults)
            for keys, _ in self._users.values():
                merged.update(keys)
            return sorted(merged)


subscriptions = SubscriptionRegistry()
