import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger("config")

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
    # How often the supervisor thread re-reads the subscription registry.
    STREAMER_SYNC_SECONDS: float = float(os.getenv("STREAMER_SYNC_SECONDS", "15"))

    # Authentication (SPEC-AUTH). ENV=production refuses AUTH_DISABLED.
    ENV: str = os.getenv("ENV", "development")
    CLERK_ISSUER: str = os.getenv("CLERK_ISSUER", "")
    AUTH_DISABLED: bool = os.getenv("AUTH_DISABLED", "false").lower() == "true"
    DEV_USER_ID: str = os.getenv("DEV_USER_ID", "dev-local")

    # Abuse limits (GAP-10). 0 disables a limit.
    MUTATION_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("MUTATION_RATE_LIMIT_PER_MINUTE", "60"))
    MAX_TRADES_PER_USER: int = int(os.getenv("MAX_TRADES_PER_USER", "2000"))
    MAX_STRATEGIES_PER_USER: int = int(os.getenv("MAX_STRATEGIES_PER_USER", "50"))
    MAX_EMOTIONS_PER_USER: int = int(os.getenv("MAX_EMOTIONS_PER_USER", "50"))
    MAX_WATCHLIST_KEYS: int = int(os.getenv("WATCHLIST_MAX_KEYS", "25"))
    # A watchlist stops pinning stream slots once its owner has been idle this long.
    WATCHLIST_TTL_SECONDS: float = float(os.getenv("WATCHLIST_TTL_SECONDS", "3600"))

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

    def is_production(self) -> bool:
        return self.ENV.strip().lower() == "production"

    def auth_mode(self) -> str:
        """`clerk` when tokens are verified, `dev-bypass` for AUTH_DISABLED."""
        return "dev-bypass" if self.AUTH_DISABLED else "clerk"

    def validate_auth_config(self) -> None:
        """Fail fast on configurations that are insecure or unusable."""
        if self.AUTH_DISABLED and self.is_production():
            raise RuntimeError(
                "AUTH_DISABLED=true is refused when ENV=production. "
                "Set CLERK_ISSUER and unset AUTH_DISABLED before deploying."
            )
        if not self.AUTH_DISABLED and not self.CLERK_ISSUER:
            # Fail closed rather than open: requests stay 401 until it is set.
            logger.error(
                "CLERK_ISSUER is not set and AUTH_DISABLED is false. "
                "Every /api request will be rejected with 401."
            )

settings = Settings()
