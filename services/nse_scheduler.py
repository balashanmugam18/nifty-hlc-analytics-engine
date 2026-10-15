from datetime import datetime, timedelta
import logging
import os
import pickle
import re
import time
import pytz
import requests

from backend.calculator import NiftyCalculatorEngine
from services.transformer import DataTransformer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(ROOT_DIR, "server_cache_metrics.pkl")


def load_cache():
    """Universal cache loader helper."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"Failed to read cache file: {e}")
    return None


def save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str):
    """Universal cache writer helper storing both Bhavcopy file date and report target date."""
    ist = pytz.timezone('Asia/Kolkata')
    cache_data = {
        "metrics": metrics,
        "excel_bytes": excel_bytes,
        "file_name": file_name,
        "file_date": file_date_str,  # Exact Bhavcopy file date (e.g., 20261015)
        "target_date": target_date_str,  # Resulting report trading date (e.g., 20261016)
        "timestamp": datetime.now(pytz.utc).astimezone(ist),
    }
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache_data, f)


def extract_date_from_filename(filename):
    """Helper to extract YYYYMMDD from NSE bhavcopy filename format."""
    match = re.search(r'(\d{8})', filename)
    return match.group(1) if match else None


def get_expected_bhavcopy_target_date():
    """
    Determines the correct NSE Bhavcopy file date based on the 20:45 (8:45 PM) IST cutoff.
    - Before 20:45 IST: Returns previous trading day.
    - After 20:45 IST: Returns today (if weekday), or preceding Friday if weekend.
    """
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(pytz.utc).astimezone(ist)

    # Cutoff time: 20:45 IST when NSE publishes the daily Bhavcopy
    cutoff_time = datetime.now(ist).replace(hour=20, minute=45, second=0, microsecond=0).time()

    if now.time() < cutoff_time:
        target = now - timedelta(days=1)
    else:
        target = now

    # Handle weekends (Saturday = 5, Sunday = 6)
    if target.weekday() == 5:  # Saturday -> Friday
        target = target - timedelta(days=1)
    elif target.weekday() == 6:  # Sunday -> Friday
        target = target - timedelta(days=2)
    elif target.weekday() == 0 and now.time() < cutoff_time:  # Monday before cutoff -> Friday
        target = target - timedelta(days=3)

    return target


def fetch_nse_bhavcopy_for_date(target_date=None, enable_weekly_zone=False):
    """
    Connects to NSE India, handles Cloudflare cookie handshakes,
    downloads the derivatives Bhavcopy ZIP for the specified target date,
    processes the calculations, and caches the results to disk.
    """
    ist = pytz.timezone('Asia/Kolkata')

    if target_date is None:
        target_date = get_expected_bhavcopy_target_date()

    file_date_str = target_date.strftime("%Y%m%d")

    # Universal cache pre-check by file_date to prevent redundant downloads
    cached_data = load_cache()
    if cached_data and cached_data.get("file_date") == file_date_str:
        logger.info(
            f"✅ Cache hit: Bhavcopy file for {file_date_str} is already cached. Skipping download & calculation.")
        return True, f"Bhavcopy for {file_date_str} is already present in cache."

    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{file_date_str}_F_0000.csv.zip"
    logger.info(f"Starting NSE Bhavcopy fetch for file date {file_date_str} (IST) from URL: {url}")

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

            output_filename = metrics.get("output_filename", "")
            target_date_str = extract_date_from_filename(output_filename) or file_date_str

            file_name = f"BhavCopy_NSE_FO_0_0_0_{file_date_str}_F_0000.csv.zip"
            save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str)

            logger.info(f"Successfully processed and cached Bhavcopy for file date {file_date_str}!")
            return True, f"Successfully processed Bhavcopy for {file_date_str}!"
        else:
            return False, f"Bhavcopy not ready on NSE yet (HTTP Status: {response.status_code})."

    except Exception as e:
        logger.error(f"Error fetching from NSE: {e}")
        return False, f"Error fetching from NSE: {e}"


def process_uploaded_bhavcopy_file(file_bytes, file_name, enable_weekly_zone=False, pdc_threshold=50):
    """
    Processes manually uploaded Bhavcopy ZIP file and caches it with pre-check.
    """
    file_date_str = extract_date_from_filename(file_name)

    cached_data = load_cache()
    if cached_data and file_date_str and cached_data.get("file_date") == file_date_str:
        logger.info(f"✅ Cache hit: Bhavcopy file for {file_date_str} is already active in cache.")
        return True, f"Bhavcopy for {file_date_str} is already active in cache."

    try:
        logger.info(f"Processing uploaded Bhavcopy file: {file_name}")
        engine = NiftyCalculatorEngine(
            file_bytes, enable_weekly_zone=enable_weekly_zone, pdc_threshold=pdc_threshold
        )
        metrics = engine.process_bhavcopy()

        transformer = DataTransformer(metrics)
        excel_bytes = transformer.generate_excel_bytes()

        if not file_date_str:
            file_date_str = datetime.now(pytz.utc).astimezone(pytz.timezone('Asia/Kolkata')).strftime("%Y%m%d")

        output_filename = metrics.get("output_filename", "")
        target_date_str = extract_date_from_filename(output_filename) or file_date_str

        save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str)
        logger.info(f"Successfully processed and cached uploaded file: {file_name} (File Date: {file_date_str})")
        return True, "Uploaded Bhavcopy processed and cached successfully!"

    except Exception as e:
        logger.error(f"Error processing uploaded file: {e}")
        return False, f"Error processing file: {e}"