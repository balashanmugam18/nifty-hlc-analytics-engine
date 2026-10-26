import os
import logging
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

logger = logging.getLogger(__name__)

def get_database_url():
    """Retrieves and validates the database connection string from environment variables."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is missing from environment variables.")
        raise ValueError("DATABASE_URL environment variable is not set.")
    return db_url

def get_db_engine():
    """Creates and returns a SQLAlchemy engine connected to Neon PostgreSQL."""
    try:
        db_url = get_database_url()
        # Create engine with connection pooling settings suitable for cloud DBs
        engine = create_engine(db_url, pool_pre_ping=True)
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        raise e