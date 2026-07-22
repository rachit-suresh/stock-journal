import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

logger = logging.getLogger("database")

class DatabaseManager:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

db_manager = DatabaseManager()

async def connect_to_mongo():
    logger.info(f"Connecting to MongoDB at {settings.MONGO_URI}...")
    try:
        db_manager.client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=2000)
        db_manager.db = db_manager.client[settings.MONGO_DB_NAME]
        logger.info(f"Successfully initialized MongoDB database connection: '{settings.MONGO_DB_NAME}'")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")

async def close_mongo_connection():
    if db_manager.client:
        logger.info("Closing MongoDB connection...")
        db_manager.client.close()

def get_database() -> AsyncIOMotorDatabase:
    return db_manager.db
