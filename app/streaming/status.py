"""Process-wide view of the market data streamer for GET /health.

The streamer runs in a daemon thread, so it reports through this module
instead of being inspected directly by request handlers.
"""

import threading
import time
from typing import Optional

_lock = threading.Lock()
_state = {
    "mode": "starting",     # "upstox" | "mock"
    "connected": False,
    "updated_at": 0.0,
}


def mark(mode: Optional[str] = None, connected: Optional[bool] = None) -> None:
    with _lock:
        if mode is not None:
            _state["mode"] = mode
        if connected is not None:
            _state["connected"] = connected
        _state["updated_at"] = time.time()


def snapshot() -> dict:
    with _lock:
        return {
            "mode": _state["mode"],
            "connected": _state["connected"],
            "updated_at": int(_state["updated_at"] * 1000) if _state["updated_at"] else None,
        }
