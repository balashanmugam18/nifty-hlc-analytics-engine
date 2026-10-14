from datetime import datetime, timedelta
import logging
import os
import pickle
import time
from apscheduler.schedulers.background import BackgroundScheduler
import requests

from backend.calculator import NiftyCalculatorEngine
from services.transformer import DataTransformer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

CACHE_FILE = "server_cache_metrics.pkl"


def fetch_nse_bhavcopy_for_date(target_date=None, enable_weekly_zone=False):
    if target_date is None:
        target_date = datetime.now()

    date_str = target_date.strftime("%Y%m%d")
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"

    logger.info(f"Starting NSE Bhavcopy fetch for {date_str} from URL: {url}")

    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
                " like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.nseindia.com/all-reports-derivatives",
        })

        logger.info("Visiting https://www.nseindia.com/all-reports-derivatives to establish session cookies...")
        session.get("https://www.nseindia.com/all-reports-derivatives", timeout=10)
        time.sleep(2)

        logger.info("Downloading Bhavcopy ZIP...")
        response = session.get(url, timeout=15)
        logger.info(f"Response Status Code: {response.status_code}")

        if response.status_code == 200:
            file_bytes = response.content
            logger.info(f"Successfully downloaded {len(file_bytes)} bytes. Processing metrics...")

            engine = NiftyCalculatorEngine(
                file_bytes, enable_weekly_zone=enable_weekly_zone, pdc_threshold=50
            )
            metrics = engine.process_bhavcopy()

            transformer = DataTransformer(metrics)
            excel_bytes = transformer.generate_excel_bytes()

            cache_data = {
                "metrics": metrics,
                "excel_bytes": excel_bytes,
                "file_name": f"Nifty_ATM_Analysis_{date_str}.xlsx",
                "target_date": date_str,  # Stored explicitly for date validation
                "timestamp": datetime.now(),
            }
            with open(CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f)

            logger.info(f"Successfully processed and cached Bhavcopy for {date_str}!")
            return True, f"Successfully processed Bhavcopy for {date_str}!"
        else:
            return False, f"Bhavcopy not ready on NSE yet (HTTP Status: {response.status_code})."

    except Exception as e:
        logger.error(f"Error fetching from NSE: {e}")
        return False, f"Error fetching from NSE: {e}"


def auto_fetch_job():
    logger.info("⏰ Background cron job triggered for NSE auto-fetch.")
    today = datetime.now()

    if today.weekday() >= 5:
        logger.info("Today is a weekend. Skipping background fetch.")
        return

    # Determine the expected previous trading day
    if today.weekday() == 0:
        target_date = today - timedelta(days=3)  # Monday morning targets Friday
    else:
        target_date = today - timedelta(days=1)  # Tuesday-Friday morning targets yesterday

    expected_date_str = target_date.strftime("%Y%m%d")
    expected_filename = f"Nifty_ATM_Analysis_{expected_date_str}.xlsx"

    # 🔍 Check server cache file BEFORE triggering any network download
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                cached_data = pickle.load(f)
                cached_target_date = cached_data.get("target_date")
                cached_filename = cached_data.get("file_name")

                # If cache already holds the exact expected previous trading day's data, skip!
                if cached_target_date == expected_date_str or cached_filename == expected_filename:
                    logger.info(
                        f"✅ Cache verification successful: Bhavcopy for {expected_date_str} "
                        f"is already present in server cache. Skipping redundant fetch."
                    )
                    return
                else:
                    logger.info(
                        f"⚠️ Cache found, but date ({cached_target_date}) does not match "
                        f"expected previous trading day ({expected_date_str}). Proceeding with fetch."
                    )
        except Exception as e:
            logger.warning(f"Could not read cache file properly: {e}. Proceeding with fetch.")

    # If cache is missing or outdated, proceed with fetching the previous trading day
    success, msg = fetch_nse_bhavcopy_for_date(target_date, enable_weekly_zone=False)
    logger.info(f"[NSE Auto-Fetcher Cron Result]: {msg}")


def init_scheduler():
    if "scheduler_started" not in os.environ:
        scheduler = BackgroundScheduler()

        # Evening cron job at 8:45 PM (Mon-Fri)
        scheduler.add_job(
            auto_fetch_job,
            "cron",
            hour=20,
            minute=45,
            day_of_week="mon-fri",
        )

        # Morning fallback cron job at 8:00 AM (Mon-Fri)
        scheduler.add_job(
            auto_fetch_job,
            "cron",
            hour=8,
            minute=0,
            day_of_week="mon-fri",
        )

        scheduler.start()
        os.environ["scheduler_started"] = "true"
        logger.info("APScheduler background cron job initialized successfully.")