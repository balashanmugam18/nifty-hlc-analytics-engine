import json
import base64
import logging
import pytz
from sqlalchemy import text
from database.db_connection import get_db_engine
from datetime import datetime, timedelta
from constants.market_constants import MARKET_HOLIDAYS
logger = logging.getLogger(__name__)


def save_daily_cache_to_db(metrics, excel_bytes, file_name, file_date_str, target_date_str):
    """
    Saves or updates daily analytics and excel bytes into hlc.daily_levels
    keyed by the report target date.
    """
    try:
        engine = get_db_engine()
        metrics_json = json.dumps(metrics, default=str)
        excel_b64 = base64.b64encode(excel_bytes).decode('utf-8')

        with engine.begin() as conn:
            conn.execute(text("""
                              INSERT INTO hlc.daily_levels (target_date, metrics_json, excel_bytes, file_name)
                              VALUES (:target_date, :metrics_json, decode(:excel_b64, 'base64'), :file_name) ON CONFLICT (target_date) 
                DO
                              UPDATE SET
                                  metrics_json = EXCLUDED.metrics_json,
                                  excel_bytes = EXCLUDED.excel_bytes,
                                  file_name = EXCLUDED.file_name,
                                  updated_at = CURRENT_TIMESTAMP;
                              """), {
                             "target_date": target_date_str,  # Explicitly using target_date_str as the unique key
                             "metrics_json": metrics_json,
                             "excel_b64": excel_b64,
                             "file_name": file_name
                         })
        logger.info(f"✅ Daily cache for target date {target_date_str} (File Date: {file_date_str}) saved to DB.")
    except Exception as e:
        logger.error(f"Error saving daily cache to DB: {e}")


def load_daily_cache_from_db(target_date=None, max_age_hours=24):
    try:
        engine = get_db_engine()
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)

        logger.info(
            f"🔍 [DB Cache Load] Checking cache for target_date: {target_date if target_date else 'LATEST (Fallback)'}")

        with engine.connect() as conn:
            if target_date:
                result = conn.execute(text("""
                                           SELECT metrics_json,
                                                  encode(excel_bytes, 'base64'),
                                                  file_name,
                                                  target_date,
                                                  updated_at
                                           FROM hlc.daily_levels
                                           WHERE target_date = :target_date;
                                           """), {"target_date": target_date}).fetchone()
            else:
                # Fallback to the latest chronological trading target date
                result = conn.execute(text("""
                                           SELECT metrics_json,
                                                  encode(excel_bytes, 'base64'),
                                                  file_name,
                                                  target_date,
                                                  updated_at
                                           FROM hlc.daily_levels
                                           ORDER BY target_date DESC LIMIT 1;
                                           """)).fetchone()

            if result:
                metrics = json.loads(result[0])
                excel_bytes = base64.b64decode(result[1])
                file_name = result[2]
                t_date = result[3]
                updated_at = result[4]

                logger.info(f"✅ [DB Cache Hit] Loaded cache for Target Date: {t_date} | File Name: {file_name}")

                return {
                    "metrics": metrics,
                    "excel_bytes": excel_bytes,
                    "file_name": file_name,
                    "file_date": t_date,
                    "target_date": t_date,
                    "timestamp": updated_at
                }
    except Exception as e:
        logger.error(f"❌ [DB Cache Error] Error loading cache from DB: {e}")
    return None


def load_active_weekly_levels_from_db():
    """Fetches the latest active weekly levels and its calculation target date from PostgreSQL."""
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                                       SELECT expiry_date,
                                              target_date,
                                              nifty_close,
                                              max_resistance,
                                              min_resistance,
                                              previous_weekly_close,
                                              min_support,
                                              max_support,
                                              updated_at
                                       FROM hlc.weekly_levels
                                       ORDER BY updated_at DESC LIMIT 1;
                                       """)).fetchone()

            if result:
                return {
                    "expiry_date": result[0],
                    "target_date": result[1],
                    "nifty_close": result[2],
                    "max_resistance": result[3],
                    "min_resistance": result[4],
                    "previous_weekly_close": result[5],
                    "min_support": result[6],
                    "max_support": result[7],
                    "updated_at": result[8]
                }
    except Exception as e:
        logger.error(f"Error loading active weekly levels from DB: {e}")
    return None


def evaluate_and_save_weekly_levels(metrics):
    """
    Evaluates and saves weekly levels into hlc.weekly_levels table.
    CRITICAL RULE: Once weekly levels are established for an expiry cycle,
    they are locked and will NEVER be overwritten by subsequent daily files.
    """
    try:
        engine = get_db_engine()
        formatted_expiry = metrics.get("formatted_expiry_str")  # e.g., "27-10-2026"

        if not formatted_expiry:
            return

        expiry_date_obj = datetime.strptime(formatted_expiry, "%d-%m-%Y")
        expiry_str_db = expiry_date_obj.strftime("%Y%m%d")

        weekly_vals = metrics.get("weekly_calculated_values", [])
        if not weekly_vals or any(v is None for v in weekly_vals):
            logger.info(f"ℹ️ Weekly zone calculation was disabled or empty for expiry {formatted_expiry}.")
            return

        with engine.connect() as conn:
            # Check if record already exists for this expiry date
            existing = conn.execute(text("""
                SELECT expiry_date FROM hlc.weekly_levels WHERE expiry_date = :expiry_date;
            """), {"expiry_date": expiry_str_db}).fetchone()

            if existing:
                # 🛑 LOCK ACTIVE: Weekly levels already exist for this expiry.
                # Do NOT overwrite them with later-day market data!
                logger.info(f"ℹ️ Weekly levels for expiry {formatted_expiry} are already locked in DB. Skipping overwrite.")
                return

            # Insert new weekly levels only if they don't exist yet (first-time baseline setup)
            conn.execute(text("""
                INSERT INTO hlc.weekly_levels (target_date, expiry_date, max_resistance, min_resistance, previous_weekly_close, min_support, max_support, updated_at)
                VALUES (:target_date, :expiry_date, :max_res, :min_res, :prev_close, :min_sup, :max_sup, CURRENT_TIMESTAMP);
            """), {
                "target_date": metrics.get("target_date", expiry_str_db),
                "expiry_date": expiry_str_db,
                "max_res": weekly_vals[0],
                "min_res": weekly_vals[1],
                "prev_close": weekly_vals[2],
                "min_sup": weekly_vals[3],
                "max_sup": weekly_vals[4]
            })
            conn.commit()
            logger.info(f"✅ Baseline weekly levels successfully locked and saved for expiry: {formatted_expiry}")

    except Exception as e:
        logger.error(f"❌ Error evaluating and saving weekly levels: {e}")

def is_next_trading_day(expiry_date_obj, file_date_obj):
    """
    Checks if file_date_obj is the exact next valid trading session
    after expiry_date_obj, skipping weekends and market holidays.
    """
    current_date = expiry_date_obj + timedelta(days=1)

    while current_date.weekday() >= 5 or current_date.strftime('%Y%m%d') in MARKET_HOLIDAYS:
        current_date += timedelta(days=1)

    return current_date.date() == file_date_obj.date()