from datetime import datetime, timedelta
import logging
import os
import pickle
import pytz
from backend.calculator import fetch_nse_bhavcopy_for_date,CACHE_FILE

# CACHE_FILE = "server_cache_metrics.pkl"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist)
    
    if today.weekday() >= 5:
        logger.info("Today is a weekend. Skipping fetch execution.")
        return

    if today.weekday() == 0:
        target_date = today - timedelta(days=3)  # Monday morning targets Friday
    else:
        target_date = today - timedelta(days=1)  # Tue-Fri targets yesterday

    expected_date_str = target_date.strftime("%Y%m%d")
    expected_filename = f"Nifty_ATM_Analysis_{expected_date_str}.xlsx"

    # Check server cache to see if the evening job already fetched and cached it
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                cached_data = pickle.load(f)
                if cached_data.get("target_date") == expected_date_str or cached_data.get("file_name") == expected_filename:
                    logger.info(
                        f"✅ Cache verification successful: Bhavcopy for {expected_date_str} "
                        f"is already present in server cache. Skipping redundant fetch."
                    )
                    return
        except Exception as e:
            logger.warning(f"Could not read cache file properly: {e}. Proceeding with fetch.")

    logger.info(f"Starting scheduled fetch for target date (IST): {target_date.strftime('%Y-%m-%d')}")
    
    success, msg = fetch_nse_bhavcopy_for_date(target_date, enable_weekly_zone=False)
    
    if success:
        logger.info(f"SUCCESS: {msg}")
    else:
        logger.error(f"FAILED: {msg}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()