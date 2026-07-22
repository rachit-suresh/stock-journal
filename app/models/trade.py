from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone

class TradeCreate(BaseModel):
    symbol: str = Field(..., description="Uppercase symbol ticker e.g. SBIN, AAPL")
    side: str = Field("BUY", description="'BUY' or 'SELL'")
    price: float = Field(..., gt=0, description="Entry execution price")
    stopLoss: Optional[float] = Field(None, description="Optional stop loss level")
    shares: int = Field(..., gt=0, description="Position unit size")
    pfMatrix: Optional[float] = Field(None, description="Profit factor ratio")
    rsMatrix: Optional[float] = Field(None, description="Relative strength ratio")
    xPercentage: Optional[float] = Field(None, description="Risk allocation %")
    strategy: str = Field("Uncategorized", description="Strategy category tag")
    emotion: str = Field("Neutral", description="Mindset profile tag")
    mistakes: List[str] = Field(default_factory=lambda: ["None"], description="Mistakes tag list")
    notes: Optional[str] = Field("", description="Detailed trade analysis notes")
    date: Optional[str] = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO timestamp")

class TradeUpdate(BaseModel):
    symbol: Optional[str] = None
    side: Optional[str] = None
    price: Optional[float] = None
    stopLoss: Optional[float] = None
    shares: Optional[int] = None
    pfMatrix: Optional[float] = None
    rsMatrix: Optional[float] = None
    xPercentage: Optional[float] = None
    strategy: Optional[str] = None
    emotion: Optional[str] = None
    mistakes: Optional[List[str]] = None
    notes: Optional[str] = None

class TradeResponse(TradeCreate):
    id: str = Field(..., alias="id")

    model_config = ConfigDict(populate_by_name=True)
