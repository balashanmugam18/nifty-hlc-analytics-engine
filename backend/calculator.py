from datetime import datetime, timedelta
import io
import logging
import math
import pytz
import re
import zipfile
import pandas as pd
import requests
import time
from curl_cffi import requests as impersonate_requests
from services.transformer import DataTransformer
from database.db_handler import (
    save_daily_cache_to_db,
    load_daily_cache_from_db,
    evaluate_and_save_weekly_levels
)
from constants.market_constants import MARKET_HOLIDAYS

logger = logging.getLogger(__name__)


def load_cache(target_date=None):
    try:
        db_data = load_daily_cache_from_db(target_date=target_date)
        if db_data:
            return db_data
    except Exception as e:
        logger.warning(f"Failed to read cache from database: {e}")
    return None

def check_if_target_date_exists_in_db(target_date_str):
    """
    Directly checks database to see if a report for this target date already exists.
    """
    try:
        cached_record = load_daily_cache_from_db(target_date=target_date_str)
        if cached_record:
            return cached_record
    except Exception as e:
        logger.warning(f"Could not verify target date in DB: {e}")
    return None

def save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str):
    """
    Universal cache writer helper storing both Bhavcopy file date and report target date
    directly into PostgreSQL database.
    """
    try:
        # Pass both file_date_str and target_date_str explicitly
        save_daily_cache_to_db(metrics, excel_bytes, file_name, file_date_str, target_date_str)

        evaluate_and_save_weekly_levels(metrics)
        logger.info(f"Successfully saved cache and metrics to database for target date: {target_date_str}")
    except Exception as e:
        logger.error(f"Failed to save cache to database: {e}")


def process_uploaded_bhavcopy_file(file_bytes, file_name, enable_weekly_zone=False, pdc_threshold=50):
    file_date_str = extract_date_from_filename(file_name)
    if not file_date_str:
        file_date_str = datetime.now(pytz.utc).astimezone(pytz.timezone('Asia/Kolkata')).strftime("%Y%m%d")

    # Determine target output date beforehand to check DB
    file_trade_date = datetime.strptime(file_date_str, '%Y%m%d')
    output_target_date = file_trade_date + timedelta(days=1)
    while output_target_date.weekday() >= 5 or output_target_date.strftime('%Y%m%d') in MARKET_HOLIDAYS:
        output_target_date += timedelta(days=1)
    target_date_str = output_target_date.strftime('%Y%m%d')

    logger.info(
        f"📂 [Upload Triggered] File Name: {file_name} | File Date: {file_date_str} | Target Date: {target_date_str}")

    # 🛑 SMART DB CHECK: If target date already exists in DB, skip reprocessing!
    existing_record = check_if_target_date_exists_in_db(target_date_str)
    if existing_record:
        logger.info(
            f"✅ Cache hit: Target date {target_date_str} is already stored in database. Skipping recalculation.")
        return True, f"Bhavcopy for target date {target_date_str} is already present in database.", target_date_str

    try:
        logger.info(f"Processing uploaded Bhavcopy file: {file_name} (Date: {file_date_str})")
        engine = NiftyCalculatorEngine(
            file_bytes, enable_weekly_zone=enable_weekly_zone, pdc_threshold=pdc_threshold
        )
        metrics = engine.process_bhavcopy()

        transformer = DataTransformer(metrics)
        excel_bytes = transformer.generate_excel_bytes()

        save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str)

        logger.info(
            f"✅ [Upload Success] Uploaded Bhavcopy for date {file_date_str} processed and saved to DB successfully.")
        return True, f"Bhavcopy for target date {target_date_str} processed and cached successfully!", target_date_str

    except Exception as e:
        logger.error(f"❌ [Upload Error] Failed processing uploaded file {file_name}: {e}")
        return False, f"Error processing file: {e}", None

def fetch_nse_bhavcopy_for_date(target_date=None, enable_weekly_zone=False):
    ist = pytz.timezone('Asia/Kolkata')

    if target_date is None:
        target_date = get_expected_bhavcopy_target_date()

    file_date_str = target_date.strftime("%Y%m%d")

    # Calculate target trading date for this fetch
    output_target_date = target_date + timedelta(days=1)
    while output_target_date.weekday() >= 5 or output_target_date.strftime('%Y%m%d') in MARKET_HOLIDAYS:
        output_target_date += timedelta(days=1)
    target_date_str = output_target_date.strftime('%Y%m%d')

    logger.info(f"🚀 [NSE Fetch Triggered] File Date: {file_date_str} | Target Date: {target_date_str}")

    # 🛑 SMART DB CHECK: Skip downloading if target date already exists in DB
    existing_record = check_if_target_date_exists_in_db(target_date_str)
    if existing_record:
        logger.info(f"✅ Cache hit: Target date {target_date_str} already exists in database. Skipping NSE download.")
        return True, f"Bhavcopy for target date {target_date_str} is already present in database.", target_date_str

    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{file_date_str}_F_0000.csv.zip"
    logger.info(f"Starting NSE Bhavcopy fetch from URL: {url}")

    # try:
    #     session = requests.Session()
    #     session.headers.update({
    #         "User-Agent": (
    #             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
    #             " like Gecko) Chrome/122.0.0.0 Safari/537.36"
    #         ),
    #         "Accept": (
    #             "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    #         ),
    #         "Accept-Language": "en-US,en;q=0.5",
    #         "Referer": "https://www.nseindia.com/all-reports-derivatives",
    #     })
    #
    #     logger.info("Visiting https://www.nseindia.com/all-reports-derivatives to establish session cookies...")
    #     session.get("https://www.nseindia.com/all-reports-derivatives", timeout=10)
    #     time.sleep(2)
    #
    #     logger.info("Downloading Bhavcopy ZIP...")
    #     response = session.get(url, timeout=15)
    #     logger.info(f"Response Status Code: {response.status_code}")
    try:
        # Impersonate a real Chrome 120 browser at the TLS/socket level
        session = impersonate_requests.Session(impersonate="chrome120")
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })

        # Step 1: Visit home page to gather initial cookies
        logger.info("Visiting homepage to establish TLS & session cookies...")
        session.get("https://www.nseindia.com/", timeout=10)
        time.sleep(2)

        # Step 2: Download Bhavcopy ZIP
        logger.info("Downloading Bhavcopy ZIP...")
        response = session.get(url, timeout=15)
        logger.info(f"Response Status Code: {response.status_code}")

        if response.status_code == 200:
            file_bytes = response.content
            logger.info(f"Successfully downloaded {len(file_bytes)} bytes. Processing metrics...")
            file_name = f"BhavCopy_NSE_FO_0_0_0_{file_date_str}_F_0000.csv.zip"

            engine = NiftyCalculatorEngine(
                file_bytes, enable_weekly_zone=enable_weekly_zone, pdc_threshold=50
            )
            metrics = engine.process_bhavcopy()

            transformer = DataTransformer(metrics)
            excel_bytes = transformer.generate_excel_bytes()

            save_cache(metrics, excel_bytes, file_name, file_date_str, target_date_str)

            logger.info(f"✅ [NSE Fetch Success] Bhavcopy for date {file_date_str} fetched and stored.")
            return True, f"Successfully processed Bhavcopy for target date {target_date_str}!", target_date_str
        else:
            return False, f"Bhavcopy not ready on NSE yet (HTTP Status: {response.status_code}).", None

    except Exception as e:
        logger.error(f"Error fetching from NSE: {e}")
        return False, f"Error fetching from NSE: {e}", None


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

class NiftyCalculatorEngine:

    def __init__(
            self, uploaded_file_bytes, enable_weekly_zone=False, pdc_threshold=50
    ):
        self.uploaded_file_bytes = uploaded_file_bytes
        self.enable_weekly_zone = enable_weekly_zone
        self.pdc_threshold = pdc_threshold

    def process_bhavcopy(self):
        logger.info("Starting Bhavcopy processing in NiftyCalculatorEngine...")

        # Step 1 & 2: Open ZIP from memory bytes and extract metadata
        try:
            with zipfile.ZipFile(
                    io.BytesIO(self.uploaded_file_bytes), 'r'
            ) as z:
                csv_file_name = z.namelist()[0]
                logger.info(f"Successfully opened ZIP. CSV file inside: {csv_file_name}")

                # Extract 8-digit date from filename
                date_match = re.search(r'(\d{8})', csv_file_name)
                if date_match:
                    raw_date_str = date_match.group(1)
                    file_trade_date = datetime.strptime(raw_date_str, '%Y%m%d')

                    # Calculate next working day, skipping weekends and holidays
                    output_target_date = file_trade_date + timedelta(days=1)
                    while output_target_date.weekday() >= 5 or output_target_date.strftime('%Y%m%d') in MARKET_HOLIDAYS:
                        output_target_date += timedelta(days=1)

                    formatted_out_date = output_target_date.strftime('%Y%m%d')
                else:
                    formatted_out_date = datetime.now().strftime('%Y%m%d')
                    file_trade_date = datetime.now()

                output_filename = f'Nifty_ATM_Analysis_{formatted_out_date}.xlsx'
                logger.info(f"Target output filename set to: {output_filename}")

                # Check delimiter structure
                preview_df = pd.read_csv(
                    z.open(csv_file_name), sep='|', nrows=2, engine='python'
                )
                if len(preview_df.columns) <= 1:
                    df = pd.read_csv(z.open(csv_file_name), sep=',', engine='python')
                    logger.info("Detected comma (,) delimited CSV structure.")
                else:
                    df = pd.read_csv(z.open(csv_file_name), sep='|', engine='python')
                    logger.info("Detected pipe (|) delimited CSV structure.")
        except Exception as e:
            logger.error(f"CRITICAL ERROR reading ZIP file: {e}")
            raise ValueError(f'CRITICAL ERROR reading ZIP file: {e}')

        # Clean up column headers
        df.columns = df.columns.str.strip()

        col_mapping = {}
        for col in df.columns:
            col_upper = col.upper()
            if 'SYMBOL' in col_upper or 'TCKRSYMB' in col_upper:
                col_mapping['Symbol'] = col
            elif 'XPRYDT' in col_upper or 'EXPIRY' in col_upper:
                col_mapping['Expiry'] = col
            elif (
                    'STRKPRIC' in col_upper
                    or 'STRIKE' in col_upper
                    or 'STRIPRIC' in col_upper
            ):
                col_mapping['Strike'] = col
            elif 'OPNTP' in col_upper or 'OPTION' in col_upper or 'OPTNTP' in col_upper:
                col_mapping['OptType'] = col
            elif 'CLSPRIC' in col_upper or 'CLOSE' in col_upper:
                col_mapping['Close'] = col
            elif 'OPNPRIC' in col_upper or 'OPEN' in col_upper:
                col_mapping['Open'] = col
            elif 'HGHPRIC' in col_upper or 'HIGH' in col_upper:
                col_mapping['High'] = col
            elif 'LWPRIC' in col_upper or 'LOW' in col_upper:
                col_mapping['Low'] = col
            elif (
                    'UNDRLYGPRIC' in col_upper
                    or 'UNDERLYING_PRICE' in col_upper
                    or 'UNDERLYING' in col_upper
            ):
                col_mapping['Underlying'] = col

        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()

        # Step 3: Validate Nifty data content
        nifty_mask = df[col_mapping['Symbol']].str.upper() == 'NIFTY'
        if not nifty_mask.any():
            logger.error("No data found for 'NIFTY' symbol in the uploaded file.")
            raise ValueError("No data found for 'NIFTY' symbol in the uploaded file.")

        # Step 4: Parse dates and filter nearest option expiry
        options_mask = df[col_mapping['OptType']].isin(['CE', 'PE'])
        df_options = df[nifty_mask & options_mask].copy()

        df_options['Parsed_Expiry'] = pd.to_datetime(
            df_options[col_mapping['Expiry']], format='%Y-%m-%d', errors='coerce'
        )
        df_options = df_options.dropna(subset=['Parsed_Expiry'])

        trade_date_ts = pd.Timestamp(file_trade_date.date())
        df_options = df_options[df_options['Parsed_Expiry'] > trade_date_ts]

        if df_options.empty:
            logger.error("No valid future expiry dates found.")
            raise ValueError('No valid future expiry dates found.')

        closest_expiry = df_options['Parsed_Expiry'].min()
        df_filtered = df_options[df_options['Parsed_Expiry'] == closest_expiry]
        formatted_expiry_str = closest_expiry.strftime('%d-%m-%Y')
        logger.info(f"Locked onto closest expiry date: {formatted_expiry_str}")

        # Step 5: Merge CE and PE options side-by-side
        ce_df = df_filtered[df_filtered[col_mapping['OptType']] == 'CE'][
            [
                col_mapping['Strike'],
                col_mapping['Close'],
                col_mapping.get('High', ''),
                col_mapping.get('Low', ''),
            ]
        ].copy()
        pe_df = df_filtered[df_filtered[col_mapping['OptType']] == 'PE'][
            [
                col_mapping['Strike'],
                col_mapping['Close'],
                col_mapping.get('High', ''),
                col_mapping.get('Low', ''),
            ]
        ].copy()

        ce_df[col_mapping['Close']] = pd.to_numeric(
            ce_df[col_mapping['Close']], errors='coerce'
        )
        pe_df[col_mapping['Close']] = pd.to_numeric(
            pe_df[col_mapping['Close']], errors='coerce'
        )
        ce_df[col_mapping.get('High', '')] = pd.to_numeric(
            ce_df[col_mapping.get('High', '')], errors='coerce'
        )
        pe_df[col_mapping.get('High', '')] = pd.to_numeric(
            pe_df[col_mapping.get('High', '')], errors='coerce'
        )
        ce_df[col_mapping.get('Low', '')] = pd.to_numeric(
            ce_df[col_mapping.get('Low', '')], errors='coerce'
        )
        pe_df[col_mapping.get('Low', '')] = pd.to_numeric(
            pe_df[col_mapping.get('Low', '')], errors='coerce'
        )

        ce_df = ce_df.rename(
            columns={
                col_mapping['Close']: 'CE_CLOSE_VALUE',
                col_mapping.get('High', ''): 'CE_HIGH_VALUE',
                col_mapping.get('Low', ''): 'CE_LOW_VALUE',
            }
        )
        pe_df = pe_df.rename(
            columns={
                col_mapping['Close']: 'PE_CLOSE_VALUE',
                col_mapping.get('High', ''): 'PE_HIGH_VALUE',
                col_mapping.get('Low', ''): 'PE_LOW_VALUE',
            }
        )

        final_df = pd.merge(ce_df, pe_df, on=col_mapping['Strike'], how='inner')
        final_df['DIFFERENCE_IN_CLOSE_VALUE'] = (
                final_df['CE_CLOSE_VALUE'] - final_df['PE_CLOSE_VALUE']
        ).abs()

        final_df = final_df.rename(columns={col_mapping['Strike']: 'STRIKE_PRICE'})
        final_df['STRIKE_PRICE'] = pd.to_numeric(
            final_df['STRIKE_PRICE'], errors='coerce'
        )
        final_df = final_df.sort_values(by='STRIKE_PRICE').reset_index(drop=True)
        final_df.index = final_df.index + 1
        final_df.index.name = 'SL.NO'
        final_df = final_df.reset_index()

        # Step 6: Calculate ATM core metrics and support/resistance boundaries
        atm_row_final = final_df.loc[
            final_df['DIFFERENCE_IN_CLOSE_VALUE'].idxmin()
        ]
        atm_strike = float(atm_row_final['STRIKE_PRICE'])
        atm_ce_close = float(atm_row_final['CE_CLOSE_VALUE'])
        atm_pe_close = float(atm_row_final['PE_CLOSE_VALUE'])

        atm_ce_high = final_df[final_df['STRIKE_PRICE'] == atm_strike][
            'CE_HIGH_VALUE'
        ].iloc[0]
        atm_ce_low = final_df[final_df['STRIKE_PRICE'] == atm_strike][
            'CE_LOW_VALUE'
        ].iloc[0]
        atm_pe_high = final_df[final_df['STRIKE_PRICE'] == atm_strike][
            'PE_HIGH_VALUE'
        ].iloc[0]
        atm_pe_low = final_df[final_df['STRIKE_PRICE'] == atm_strike][
            'PE_LOW_VALUE'
        ].iloc[0]

        matched_source_row = df[
            nifty_mask
            & (
                    pd.to_numeric(df[col_mapping['Strike']], errors='coerce')
                    == atm_strike
            )
            ]
        nifty_close = float(matched_source_row[col_mapping['Underlying']].iloc[0])
        logger.info(f"Identified ATM Strike: {atm_strike} | Nifty Spot Close: {nifty_close}")

        min_resistance = atm_strike + atm_ce_close
        min_support = atm_strike - atm_pe_close
        total_close_value = atm_ce_close + atm_pe_close
        max_resistance = atm_strike + total_close_value
        max_support = atm_strike - total_close_value

        # Calculate Total Time Value: (ATM - 50 CE Close) + (ATM + 50 PE Close) - 100
        otm_ce_strike_for_tv = atm_strike - 50
        otm_pe_strike_for_tv = atm_strike + 50
        otm_ce_match = final_df[final_df['STRIKE_PRICE'] == otm_ce_strike_for_tv]
        otm_pe_match = final_df[final_df['STRIKE_PRICE'] == otm_pe_strike_for_tv]
        otm_ce_close_val = (
            float(otm_ce_match['CE_CLOSE_VALUE'].iloc[0])
            if not otm_ce_match.empty
            else 0.0
        )
        otm_pe_close_val = (
            float(otm_pe_match['PE_CLOSE_VALUE'].iloc[0])
            if not otm_pe_match.empty
            else 0.0
        )
        total_time_value = otm_ce_close_val + otm_pe_close_val - 100

        def calculate_status(high_price, close_price, low_price):
            diff_high_close = high_price - close_price
            diff_close_low = close_price - low_price
            wick_diff = abs(diff_close_low - diff_high_close)
            if diff_close_low > diff_high_close:
                return (
                    'Panic'
                    if (diff_close_low > 30 and wick_diff >= 10)
                    else 'Panic/Sideways'
                )
            elif diff_high_close > diff_close_low:
                return (
                    'Profit Booking'
                    if (diff_high_close > 30 and wick_diff >= 10)
                    else 'Profit Booking/Sideways'
                )
            return 'Neutral/Sideways'

        atm_ce_status = calculate_status(atm_ce_high, atm_ce_close, atm_ce_low)
        atm_pe_status = calculate_status(atm_pe_high, atm_pe_close, atm_pe_low)

        pdc_diff = abs(nifty_close - atm_strike)
        change_in_pdc_val = (
            atm_strike if pdc_diff > self.pdc_threshold else '---'
        )

        # Step 7: Process Weekly Zone matrix
        logger.info(f"Processing Weekly Zone matrix (Enabled: {self.enable_weekly_zone})")
        weekly_labels = [
            "Maximum Resistance",
            "Minimum Resistance",
            "Previous Day Close (PDC)",
            "Minimum Support",
            "Maximum Support",
        ]

        if self.enable_weekly_zone:
            weekly_atm_1 = math.floor(nifty_close / 100.0) * 100
            if nifty_close % 100 == 0:
                weekly_atm_2 = weekly_atm_1 + 100
            else:
                weekly_atm_2 = math.ceil(nifty_close / 100.0) * 100

            def fetch_straddle_value(strike):
                match = final_df[final_df['STRIKE_PRICE'] == strike]
                if match.empty:
                    return 0.0
                return float(match['CE_CLOSE_VALUE'].iloc[0]) + float(
                    match['PE_CLOSE_VALUE'].iloc[0]
                )

            atm_1_straddle = fetch_straddle_value(weekly_atm_1)
            atm_2_straddle = fetch_straddle_value(weekly_atm_2)

            line1 = weekly_atm_1 + atm_1_straddle
            line2 = weekly_atm_2 - atm_2_straddle
            weekly_pdc = nifty_close
            line3 = weekly_atm_1 - atm_1_straddle
            line4 = weekly_atm_2 + atm_2_straddle

            # Exact array sequence matching legacy version
            weekly_calculated_values = [
                line4,  # Maximum Resistance
                line1,  # Minimum Resistance
                weekly_pdc,  # Previous Day Close (PDC)
                line2,  # Minimum Support
                line3,  # Maximum Support
            ]
        else:
            weekly_calculated_values = [None] * len(weekly_labels)

        # Step 8: Execute Sniper Strategy calculation matrix
        logger.info("Executing Sniper Strategy calculations...")
        sniper_atm_base = int(round(nifty_close / 100.0) * 100)

        def fetch_row_metrics(strike_price):
            match = final_df[final_df['STRIKE_PRICE'] == strike_price]
            if match.empty:
                return {"CE_CLOSE": 0.0, "CE_HIGH": 0.0, "PE_CLOSE": 0.0, "PE_HIGH": 0.0}
            return {
                "CE_CLOSE": float(match['CE_CLOSE_VALUE'].iloc[0]),
                "CE_HIGH": float(match['CE_HIGH_VALUE'].iloc[0]),
                "PE_CLOSE": float(match['PE_CLOSE_VALUE'].iloc[0]),
                "PE_HIGH": float(match['PE_HIGH_VALUE'].iloc[0])
            }

        current_atm = sniper_atm_base
        THRESHOLD = 30.0
        max_iterations = 10
        iteration = 0
        valid_strike_found = False

        while iteration < max_iterations:
            otm_pe_metrics = fetch_row_metrics(current_atm - 100)
            otm_ce_metrics = fetch_row_metrics(current_atm + 100)
            current_sniper_val = (otm_pe_metrics["PE_CLOSE"] + otm_ce_metrics["CE_CLOSE"]) / 2.0

            atm_metrics = fetch_row_metrics(current_atm)
            ce_diff = atm_metrics["CE_CLOSE"] - current_sniper_val
            pe_diff = atm_metrics['PE_CLOSE'] - current_sniper_val

            if ce_diff >= THRESHOLD and pe_diff >= THRESHOLD:
                valid_strike_found = True
                break

            if ce_diff < pe_diff:
                current_atm -= 100
            else:
                current_atm += 100

            iteration += 1

        final_sniper_atm = current_atm

        ce_block_atm = fetch_row_metrics(final_sniper_atm)
        ce_block_otm = fetch_row_metrics(final_sniper_atm - 100)
        pe_block_atm = fetch_row_metrics(final_sniper_atm)
        pe_block_otm = fetch_row_metrics(final_sniper_atm + 100)

        # Helper to calculate individual sniper value dynamically for any given strike s
        def calculate_individual_sniper(s):
            wing_pe = fetch_row_metrics(s - 100)
            wing_ce = fetch_row_metrics(s + 100)
            return (wing_pe["PE_CLOSE"] + wing_ce["CE_CLOSE"]) / 2.0

        # Unique individual sniper calculation per strike
        atm_sniper_val = calculate_individual_sniper(final_sniper_atm)
        otm_pe_sniper_val = calculate_individual_sniper(final_sniper_atm - 100)
        otm_ce_sniper_val = calculate_individual_sniper(final_sniper_atm + 100)

        # Legacy global fallback
        final_sniper_calculation = atm_sniper_val

        # Capture diagnostic payload for all 3 strikes with individual strike snipers
        diag_strikes = [
            final_sniper_atm - 100,
            final_sniper_atm,
            final_sniper_atm + 100
        ]

        sniper_diag_rows = []
        for s in diag_strikes:
            m = fetch_row_metrics(s)
            ind_sniper = calculate_individual_sniper(s)

            if s < final_sniper_atm:
                label_prefix = f"{s} OTM (-100)"
            elif s > final_sniper_atm:
                label_prefix = f"{s} OTM (+100)"
            else:
                label_prefix = f"{s} ATM"

            # CE Row
            sniper_diag_rows.append({
                'strike_label': label_prefix,
                'type': 'CE',
                'close': m['CE_CLOSE'],
                'sniper_val': ind_sniper,
                'diff': m['CE_CLOSE'] - ind_sniper
            })
            # PE Row
            sniper_diag_rows.append({
                'strike_label': label_prefix,
                'type': 'PE',
                'close': m['PE_CLOSE'],
                'sniper_val': ind_sniper,
                'diff': m['PE_CLOSE'] - ind_sniper
            })

        logger.info("Calculation complete. Returning metrics dictionary.")
        return {
            'output_filename': output_filename,
            'formatted_expiry_str': formatted_expiry_str,
            'nifty_close': nifty_close,
            'atm_strike': atm_strike,
            'atm_ce_close': atm_ce_close,
            'atm_ce_high': atm_ce_high,
            'atm_ce_low': atm_ce_low,
            'atm_ce_status': atm_ce_status,
            'atm_pe_close': atm_pe_close,
            'atm_pe_high': atm_pe_high,
            'atm_pe_low': atm_pe_low,
            'atm_pe_status': atm_pe_status,
            'total_close_value': total_close_value,
            'total_time_value': total_time_value,
            'max_resistance': max_resistance,
            'min_resistance': min_resistance,
            'change_in_pdc_val': change_in_pdc_val,
            'min_support': min_support,
            'max_support': max_support,
            'weekly_labels': weekly_labels,
            'weekly_calculated_values': weekly_calculated_values,
            'final_sniper_atm': final_sniper_atm,
            'final_sniper_calculation': final_sniper_calculation,
            'atm_sniper_val': atm_sniper_val,
            'otm_pe_sniper_val': otm_pe_sniper_val,
            'otm_ce_sniper_val': otm_ce_sniper_val,
            'ce_block_atm': ce_block_atm,
            'ce_block_otm': ce_block_otm,
            'pe_block_atm': pe_block_atm,
            'pe_block_otm': pe_block_otm,
            "final_df": final_df,
            'sniper_threshold_met': valid_strike_found,
            'sniper_diag_rows': sniper_diag_rows
        }