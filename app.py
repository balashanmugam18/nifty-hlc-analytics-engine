from datetime import datetime
import logging
import pandas as pd
import streamlit as st

from backend.calculator import (
    fetch_nse_bhavcopy_for_date,
    process_uploaded_bhavcopy_file,
    load_cache,
)
from database.db_handler import load_active_weekly_levels_from_db
from database.db_models import init_db

# Configure root logger to output INFO level logs to the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="HLC Nifty Analysis Dashboard", layout="wide")

# Ensure database schema & tables are initialized on startup
init_db()

# Initialize session state for active target date tracking
if "active_target_date" not in st.session_state:
    st.session_state["active_target_date"] = None


# Formatting helper to ensure all table values are strings (prevents Arrow crashes)
def fmt(v):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, int):
        return str(v)
    return str(v)


# ==============================================================================
# 1. VIEW PASSWORD GATEWAY
# ==============================================================================
def check_view_password():
    try:
        correct_pass = st.secrets.get("VIEW_PASSWORD", "view123")
    except Exception:
        correct_pass = "view123"

    if st.session_state.get("view_authenticated", False):
        return True

    st.title("🔒 Restricted Access")
    entered_pass = st.text_input(
        "Enter View Password to Access Dashboard:",
        type="password",
        key="view_pass_input",
    )

    if entered_pass:
        if entered_pass == correct_pass:
            st.session_state["view_authenticated"] = True
            st.rerun()
        else:
            st.error("❌ Incorrect View Password")

    return False


if not check_view_password():
    st.stop()

# ==============================================================================
# 2. MAIN APPLICATION CONTENT & SIDEBAR
# ==============================================================================
st.title("📊 HLC Nifty Calculation & Strategy Dashboard")

st.sidebar.header("Configuration")
enable_weekly = st.sidebar.checkbox(
    "Enable Weekly Zone Calculation", value=False
)
pdc_thresh = st.sidebar.slider(
    "PDC Difference Threshold", min_value=25, max_value=150, value=50, step=25
)

# ==============================================================================
# 3. ADMIN UPLOAD & AUTO-FETCH SECTION
# ==============================================================================
st.markdown("---")
st.subheader("📂 Bhavcopy Data Management (Admin Only)")

upload_pass_input = st.text_input(
    "Enter Upload Password to unlock admin controls:",
    type="password",
    key="upload_pass_input_main",
)

try:
    correct_upload_pass = st.secrets.get("UPLOAD_PASSWORD", "upload456")
except Exception:
    correct_upload_pass = "upload456"

if upload_pass_input != correct_upload_pass:
    if upload_pass_input != "":
        st.error("⛔ Incorrect Upload Password. Admin controls remain locked.")
    else:
        st.info(
            "🔒 Enter the Upload Password above if you are Admin looking to upload"
            " or fetch new data."
        )
else:
    st.success("🔓 Admin Authorized!")

    col1, col2 = st.columns(2)

    # Manual Fetch Button (automatically respects the 20:45 IST cutoff rule)
    with col1:
        st.markdown("**Fetch Direct from NSE**")
        if st.button("🚀 Fetch Latest Bhavcopy from NSE Now"):
            with st.spinner("Checking cache and connecting to NSE..."):
                result = fetch_nse_bhavcopy_for_date(
                    enable_weekly_zone=enable_weekly
                )

                # Unpack tuple safely (handles 2 or 3 returned items)
                success = result[0]
                message = result[1]
                t_date = result[2] if len(result) > 2 else None

                if success:
                    if t_date:
                        st.session_state["active_target_date"] = t_date
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    # Manual Upload with explicit Process button & cache verification
    with col2:
        st.markdown("**Upload Bhavcopy ZIP**")
        uploaded_file = st.file_uploader(
            "Choose ZIP File",
            type=["zip"],
            key="bhav_uploader",
            label_visibility="collapsed",
        )

        if uploaded_file is not None:
            if st.button("📥 Process Uploaded File"):
                with st.spinner("Processing uploaded Bhavcopy..."):
                    file_bytes = uploaded_file.read()
                    result = process_uploaded_bhavcopy_file(
                        file_bytes,
                        uploaded_file.name,
                        enable_weekly_zone=enable_weekly,
                        pdc_threshold=pdc_thresh,
                    )

                    # Unpack tuple safely (handles 2 or 3 returned items)
                    success = result[0]
                    message = result[1]
                    t_date = result[2] if len(result) > 2 else None

                    if success:
                        if t_date:
                            st.session_state["active_target_date"] = t_date
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

# ==============================================================================
# 4. DASHBOARD UI DISPLAY
# ==============================================================================
# Load cache using the session's active target date
cached_data = load_cache(target_date=st.session_state.get("active_target_date"))

st.markdown("---")

if cached_data is None:
    logger.info("🖥️ [UI Display] Rendering state: No active cache found in DB (Showing empty state banner).")
    st.info(
        "📌 **No Bhavcopy loaded in database yet. Click 'Fetch Latest Bhavcopy from"
        " NSE Now' above or upload a ZIP file to view analytics.**"
    )
else:
    m = cached_data["metrics"]
    excel_bytes = cached_data["excel_bytes"]
    output_filename = cached_data.get("file_name", m.get("output_filename", "Nifty_ATM_Analysis"))
    target_date_val = cached_data.get("target_date", "N/A")

    try:
        clean_name = output_filename.split(".")[0]
        date_str_raw = cached_data.get("file_date", clean_name.split("_")[-1])
        formatted_date = datetime.strptime(date_str_raw, "%Y%m%d").strftime(
            "%d/%m/%Y"
        )
    except Exception:
        formatted_date = "N/A"

    logger.info(
        f"🖥️ [UI Display Success] Rendering Dashboard for Target Date: {target_date_val} | Active File: {output_filename} | Formatted Date: {formatted_date}")

    st.success(
        f"📊 **Active Analytics Report:** `{output_filename}`  \n🗓️ **Date:**"
        f" `{formatted_date}`"
    )

    # 1. KEY STRATEGY METRICS
    st.subheader("Key Strategy Metrics")
    pdc_cas_display = (
        f"~~{fmt(m['nifty_close'])}~~"
        if m.get("change_in_pdc_val", "---") != "---"
        else fmt(m["nifty_close"])
    )

    key_metrics_df = pd.DataFrame({
        "Metric": [
            "Maximum Resistance",
            "Minimum Resistance",
            "Change in PDC",
            "Previous Day Close (PDC CAS)",
            "Minimum Support",
            "Maximum Support",
            "Total Time Value",
        ],
        "Value": [
            fmt(m["max_resistance"]),
            fmt(m["min_resistance"]),
            fmt(m.get("change_in_pdc_val", "---")),
            pdc_cas_display,
            fmt(m["min_support"]),
            fmt(m["max_support"]),
            fmt(m.get("total_time_value", 0.0)),
        ],
    })
    st.table(key_metrics_df)

    st.markdown("---")

    # 2. HLC ATM LEVELS METRICS
    st.subheader("HLC ATM LEVELS Metrics")
    hlc_atm_df = pd.DataFrame({
        "Metric": [
            "At-The-Money Strike (ATM)",
            "ATM Call Close Value",
            "ATM Call High Value",
            "ATM Call Low Value",
            "ATM Call Status",
            "ATM Put Close Value",
            "ATM Put High Value",
            "ATM Put Low Value",
            "ATM Put Status",
            "Total Close Value (Straddle Premium)",
        ],
        "Value": [
            fmt(m["atm_strike"]),
            fmt(m["atm_ce_close"]),
            fmt(m["atm_ce_high"]),
            fmt(m["atm_ce_low"]),
            fmt(m["atm_ce_status"]),
            fmt(m["atm_pe_close"]),
            fmt(m["atm_pe_high"]),
            fmt(m["atm_pe_low"]),
            fmt(m["atm_pe_status"]),
            fmt(m["total_close_value"]),
        ],
        "Expiry Date": [
            m["formatted_expiry_str"] if i == 0 else "" for i in range(10)
        ],
    })
    st.table(hlc_atm_df)

    st.markdown("---")

    # 3. WEEKLY RANGE METRICS
    if enable_weekly:
        st.subheader("Weekly Range Metrics")
        weekly_db_data = load_active_weekly_levels_from_db()

        if weekly_db_data:
            raw_date = weekly_db_data.get("target_date", "")
            try:
                formatted_calc_date = datetime.strptime(raw_date, "%Y%m%d").strftime("%d/%m/%Y")
            except Exception:
                formatted_calc_date = raw_date

            st.info(
                f"🗓️ **Active Weekly Levels Generated On:** `{formatted_calc_date}` "
                f"| 🎯 **Target Expiry:** `{weekly_db_data.get('expiry_date')}`"
            )

            weekly_df = pd.DataFrame({
                "Weekly Range Level": [
                    "Maximum Resistance",
                    "Minimum Resistance",
                    "Previous Weekly Close",
                    "Minimum Support",
                    "Maximum Support",
                ],
                "Calculated Value": [
                    fmt(weekly_db_data["max_resistance"]),
                    fmt(weekly_db_data["min_resistance"]),
                    fmt(weekly_db_data["previous_weekly_close"]),
                    fmt(weekly_db_data["min_support"]),
                    fmt(weekly_db_data["max_support"]),
                ],
            })
            st.table(weekly_df)
        else:
            st.warning(
                "⚠️ No active weekly levels found in the database. "
                "Weekly levels will automatically update on the first post-expiry session."
            )
        st.markdown("---")

    # 4. SNIPER LEVELS METRICS
    st.subheader("SNIPER LEVELS METRICS")
    sniper_col1, sniper_col2 = st.columns(2)

    with sniper_col1:
        st.markdown(
            f"**ATM strike price - {m['final_sniper_atm']} CE** | "
            f" high - **{fmt(m['ce_block_atm']['CE_HIGH'])}** | "
            f" close - **{fmt(m['ce_block_atm']['CE_CLOSE'])}**"
        )
        st.markdown(f"**sniper - {fmt(m['final_sniper_calculation'])}**")
        st.markdown(
            f"**ATM strike price - {m['final_sniper_atm']} PE** | "
            f" high - **{fmt(m['pe_block_atm']['PE_HIGH'])}** | "
            f" close - **{fmt(m['pe_block_atm']['PE_CLOSE'])}**"
        )
        st.markdown(f"**sniper - {fmt(m['final_sniper_calculation'])}**")

    with sniper_col2:
        st.markdown(
            f"**OTM strike price - {m['final_sniper_atm'] - 100} PE** | "
            f" high - **{fmt(m['ce_block_otm']['PE_HIGH'])}** | "
            f" close - **{fmt(m['ce_block_otm']['PE_CLOSE'])}**"
        )
        st.write("")
        st.markdown(
            f"**OTM strike price - {m['final_sniper_atm'] + 100} CE** | "
            f" high - **{fmt(m['pe_block_otm']['CE_HIGH'])}** | "
            f" close - **{fmt(m['pe_block_otm']['CE_CLOSE'])}**"
        )

    st.markdown("---")

    # 5. EXCEL DOWNLOAD BUTTON
    st.subheader("📥 Download Prepared Excel")
    st.download_button(
        label="Download Excel Output",
        data=excel_bytes,
        file_name=output_filename,
        mime=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

    # Debug Sniper Difference Table
    threshold_met = m.get("sniper_threshold_met", True)
    diag_rows = m.get("sniper_diag_rows", [])

    show_debug_table = st.sidebar.checkbox(
        "Show Sniper Difference Metrics (Fallback Analysis)",
        value=not threshold_met,
    )

    if show_debug_table and diag_rows:
        st.warning(
            "⚠️ Sniper Strategy: Showing 6-Row Difference Metrics Matrix:"
        )

        diff_df = pd.DataFrame([
            {
                "Strike / Wing": row["strike_label"],
                "Type": row["type"],
                "Close Value": row["close"],
                "Sniper Value": row["sniper_val"],
                "Difference (Close - Sniper)": round(row["diff"], 2),
            }
            for row in diag_rows
        ])

        st.dataframe(diff_df, width='stretch', hide_index=True)