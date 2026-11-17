from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.models.trade import TradeResponse

T = TypeVar("T")


class DataResponse(BaseModel, Generic[T]):
    """`{"success": true, "data": ...}` envelope used by read/write endpoints."""

    success: bool = True
    data: T


class MessageResponse(BaseModel):
    """`{"success": true, "message": ...}` envelope for verbs without a payload."""

    success: bool = True
    message: str


class PriceMeta(BaseModel):
    """Freshness of a single cached instrument key."""

    as_of: Optional[int] = Field(None, description="Epoch ms of the last tick; null if never seen")
    stale: bool = Field(..., description="True when older than PRICE_MAX_AGE_SECONDS")


class PricesResponse(BaseModel):
    success: bool = True
    data: dict[str, float]
    meta: dict[str, PriceMeta]
    timestamp: int


class JournalOverview(BaseModel):
    trades: list[TradeResponse]
    strategies: list[str]
    emotions: list[str]


class JournalResponse(BaseModel):
    success: bool = True
    data: JournalOverview
