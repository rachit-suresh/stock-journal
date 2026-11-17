"""Abuse guards for an app with open sign-up (GAP-10).

Two cheap, single-process protections:
  * a per-user, per-IP sliding window on mutating requests, and
  * hard caps on how many rows one account may own.

Both live in memory on purpose: Render runs a single service instance, and a
restart simply refills the budget. Moving to multiple instances means moving
these counters to Mongo or Redis.
"""

import threading
import time
from collections import deque
from typing import Dict

from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.security import UserContext, get_current_user

WINDOW_SECONDS = 60.0
MAX_TRACKED_KEYS = 512

_buckets: Dict[str, deque] = {}
_lock = threading.Lock()


def _allow(key: str, limit: int) -> bool:
    now = time.monotonic()
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        while bucket and now - bucket[0] > WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= limit:
            return False

        bucket.append(now)

        if len(_buckets) > MAX_TRACKED_KEYS:
            for tracked, stamps in list(_buckets.items()):
                if not stamps or now - stamps[-1] > WINDOW_SECONDS:
                    _buckets.pop(tracked, None)
        return True


async def mutation_rate_limit(
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> None:
    """Dependency for POST/PUT/DELETE routes."""
    limit = settings.MUTATION_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return

    client_ip = request.client.host if request.client else "unknown"
    if not _allow(f"{user.user_id}:{client_ip}", limit):
        raise HTTPException(
            status_code=429,
            detail="Too many changes in a short time. Wait a minute and try again.",
            headers={"Retry-After": "60"},
        )


def enforce_cap(current: int, cap: int, label: str) -> None:
    """Refuse a create once an account already holds `cap` rows."""
    if cap > 0 and current >= cap:
        raise HTTPException(
            status_code=400,
            detail=f"{label} limit reached ({cap}). Delete an entry before adding another.",
        )


def reset_rate_limit_buckets() -> None:
    """Test helper: forget every tracked window."""
    with _lock:
        _buckets.clear()
