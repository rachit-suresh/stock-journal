import os
from dotenv import load_dotenv

# Load environmental variables from .env file if available
load_dotenv()

class Settings:
    # Application Config
    PROJECT_NAME: str = "Stock Journal Monolith"
    VERSION: str = "2.0.0"

    # Upstox Analytics Access Token: read-only, valid one year, covers Market
    # Data + Streaming. No OAuth app or daily refresh; renew before expiry.
    UPSTOX_ACCESS_TOKEN: str = os.getenv("UPSTOX_ACCESS_TOKEN", "")

    # Mode & Streamer Config
    MOCK_STREAMER: bool = os.getenv("MOCK_STREAMER", "false").lower() == "true"
    TOKENS_STR: str = os.getenv("TOKENS", "NSE_EQ|INE062A01020,NSE_EQ|INE160A01022,NSE_EQ|INE467I01027,NSE_EQ|INE009A01021,NSE_EQ|INE075A01022")
    # Cached ticks older than this are reported as stale by GET /api/prices.
    PRICE_MAX_AGE_SECONDS: float = float(os.getenv("PRICE_MAX_AGE_SECONDS", "30"))

    # CORS & Security Config
    ALLOWED_ORIGINS_STR: str = os.getenv("ALLOWED_ORIGINS", "*")

    # MongoDB Config
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "stock_journal")

    def get_allowed_origins(self) -> list[str]:
        if not self.ALLOWED_ORIGINS_STR or self.ALLOWED_ORIGINS_STR.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.ALLOWED_ORIGINS_STR.split(",") if o.strip()]

    def get_tokens(self) -> list[str]:
        if not self.TOKENS_STR:
            return []
        return [t.strip() for t in self.TOKENS_STR.split(",") if t.strip()]

    def has_upstox_credentials(self) -> bool:
        return bool(self.UPSTOX_ACCESS_TOKEN)

settings = Settings()
