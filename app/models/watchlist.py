import re
from typing import List

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

# Upstox instrument keys look like `NSE_EQ|INE062A01020` (exchange segment + ISIN).
INSTRUMENT_KEY_PATTERN = re.compile(r"^[A-Z0-9]{2,12}_[A-Z0-9]{2,8}\|[A-Z0-9]{4,20}$")


class WatchlistUpdate(BaseModel):
    keys: List[str] = Field(default_factory=list)

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, keys: List[str]) -> List[str]:
        cleaned: List[str] = []
        for raw in keys:
            key = (raw or "").strip().upper()
            if not INSTRUMENT_KEY_PATTERN.match(key):
                raise ValueError(
                    f"'{raw}' is not a valid instrument key (expected e.g. NSE_EQ|INE062A01020)."
                )
            if key not in cleaned:
                cleaned.append(key)

        cap = settings.MAX_WATCHLIST_KEYS
        if cap > 0 and len(cleaned) > cap:
            raise ValueError(f"A watchlist holds at most {cap} instruments.")
        return cleaned


class WatchlistResponse(BaseModel):
    success: bool = True
    data: List[str]
