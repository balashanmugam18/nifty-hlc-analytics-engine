import os
import logging
from sqlalchemy import create_engine
from dotenv import load_dotenv
import streamlit as st

# Load environment variables from local .env file (ignored if not present)
load_dotenv()

logger = logging.getLogger(__name__)


def get_database_url():
    """Retrieves and validates the database connection string from Streamlit secrets or local .env."""
    db_url = None

    # 1. Try fetching from Streamlit secrets (for cloud deployment)
    try:
        if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
            db_url = st.secrets["DATABASE_URL"]
    except Exception:
        pass  # st.secrets is unavailable when running scripts outside of Streamlit

    # 2. Fall back to local environment variables (.env)
    if not db_url:
        db_url = os.getenv("DATABASE_URL")

    if not db_url:
        logger.error("DATABASE_URL is missing from both Streamlit secrets and environment variables.")
        raise ValueError("DATABASE_URL configuration is missing.")

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