import os
from dotenv import load_dotenv

# Load environmental variables from .env file if available
load_dotenv()

class Settings:
    # Application Config
    PROJECT_NAME: str = "Stock Journal Monolith"
    VERSION: str = "2.0.0"

    # SmartAPI Credentials
    API_KEY: str = os.getenv("SMART_API_KEY", "")
    CLIENT_CODE: str = os.getenv("SMART_CLIENT_CODE", "")
    PASSWORD: str = os.getenv("SMART_PASSWORD", "")
    TOTP_SECRET: str = os.getenv("SMART_TOTP_SECRET", "")

    # Mode & Streamer Config
    MOCK_STREAMER: bool = os.getenv("MOCK_STREAMER", "false").lower() == "true"
    TOKENS_STR: str = os.getenv("TOKENS", "3045,2885,11536,1594,3456")

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

    def has_smart_api_credentials(self) -> bool:
        return all([self.API_KEY, self.CLIENT_CODE, self.PASSWORD, self.TOTP_SECRET])

settings = Settings()
