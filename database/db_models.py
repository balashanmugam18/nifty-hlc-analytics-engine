import logging
from sqlalchemy import text
from database.db_connection import get_db_engine

logger = logging.getLogger(__name__)


def init_db():
    """Initializes the custom 'hlc' schema and explicitly creates daily and weekly tables inside it."""
    try:
        engine = get_db_engine()
        with engine.begin() as conn:
            # 1. Force create the 'hlc' schema
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS hlc;"))

            # 2. Explicitly create daily_levels inside schema 'hlc'
            conn.execute(text("""
                              CREATE TABLE IF NOT EXISTS hlc.daily_levels
                              (
                                  id
                                  SERIAL
                                  PRIMARY
                                  KEY,
                                  target_date
                                  VARCHAR
                              (
                                  10
                              ) UNIQUE,
                                  metrics_json TEXT,
                                  excel_bytes BYTEA,
                                  file_name VARCHAR
                              (
                                  255
                              ),
                                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                  );
                              """))

            # 3. Explicitly create weekly_levels inside schema 'hlc'
            conn.execute(text("""
                              CREATE TABLE IF NOT EXISTS hlc.weekly_levels
                              (
                                  id
                                  SERIAL
                                  PRIMARY
                                  KEY,
                                  expiry_date
                                  VARCHAR
                              (
                                  10
                              ),
                                  target_date VARCHAR
                              (
                                  10
                              ) UNIQUE,
                                  nifty_close FLOAT,
                                  max_resistance FLOAT,
                                  min_resistance FLOAT,
                                  previous_weekly_close FLOAT,
                                  min_support FLOAT,
                                  max_support FLOAT,
                                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                  );
                              """))

        logger.info(
            "Schema 'hlc' and tables (daily_levels, weekly_levels) verified/created successfully in Neon PostgreSQL.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database schema and tables: {e}")
        return False