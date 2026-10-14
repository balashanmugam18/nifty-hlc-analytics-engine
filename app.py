from datetime import datetime, timedelta
import os
import pickle
import pandas as pd
import streamlit as st

from backend.calculator import NiftyCalculatorEngine
from services.nse_scheduler import fetch_nse_bhavcopy_for_date, init_scheduler
from services.transformer import DataTransformer

st.set_page_config(page_title="HLC Nifty Analysis Dashboard", layout="wide")

CACHE_FILE = "server_cache_metrics.pkl"

# Initialize background scheduler safely
try:
    init_scheduler()
except Exception as e:
    print(f"Scheduler init note: {e}")


def save_to_server_cache(metrics, excel_bytes, file_name, target_date_str):
    data = {
        "metrics": metrics,
        "excel_bytes": excel_bytes,
        "file_name": file_name,
        "target_date": target_date_str,
        "timestamp": datetime.now(),
    }
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(data, f)


def load_from_server_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                data = pickle.load(f)
                if datetime.now() - data["timestamp"] > timedelta(hours=24):
                    os.remove(CACHE_FILE)
                    return None
                return data
        except Exception:
            return None
    return None


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
    with col1:
        if st.button("🚀 Fetch & Process Latest Bhavcopy from NSE Now"):
            with st.spinner("Connecting to NSE and calculating metrics..."):
                success, message = fetch_nse_bhavcopy_for_date(
                    datetime.now(), enable_weekly_zone=enable_weekly
                )
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    with col2:
        uploaded_file = st.file_uploader(
            "Or Upload ZIP File", type=["zip"], key="bhav_uploader"
        )

    if uploaded_file is not None:
        cached_data = load_from_server_cache()
        if cached_data is None or cached_data.get("file_name") != uploaded_file.name:
            try:
                with st.spinner("Processing uploaded Bhavcopy..."):
                    file_bytes = uploaded_file.read()
                    engine = NiftyCalculatorEngine(
                        file_bytes,
                        enable_weekly_zone=enable_weekly,
                        pdc_threshold=pdc_thresh,
                    )
                    metrics = engine.process_bhavcopy()

                    transformer = DataTransformer(metrics)
                    excel_bytes = transformer.generate_excel_bytes()

                    date_str_tag = datetime.now().strftime("%Y%m%d")
                    save_to_server_cache(
                        metrics, excel_bytes, uploaded_file.name, date_str_tag
                    )
                    st.success("Bhavcopy processed successfully!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error processing file: {e}")

# ==============================================================================
# 4. DASHBOARD UI DISPLAY
# ==============================================================================
cached_data = load_from_server_cache()

st.markdown("---")

if cached_data is None:
    st.info(
        "📌 **No Bhavcopy loaded yet. Click 'Fetch & Process Latest Bhavcopy from"
        " NSE Now' above or upload a ZIP file to view analytics.**"
    )
else:
    m = cached_data["metrics"]
    excel_bytes = cached_data["excel_bytes"]
    output_filename = m.get("output_filename", "Nifty_ATM_Analysis")

    try:
        clean_name = output_filename.split(".")[0]
        date_str_raw = clean_name.split("_")[-1]
        formatted_date = datetime.strptime(date_str_raw, "%Y%m%d").strftime(
            "%d/%m/%Y"
        )
    except Exception:
        formatted_date = "N/A"

    st.success(
        f"📊 **Active Analytics Report:** `{output_filename}`  \n🗓️ **Date:**"
        f" `{formatted_date}`"
    )

    # 1. KEY STRATEGY METRICS
    st.subheader("Key Strategy Metrics")
    pdc_cas_display = (
        f"~~{fmt(m['nifty_close'])}~~"
        if m["change_in_pdc_val"] != "---"
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
            fmt(m["change_in_pdc_val"]),
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
        weekly_labels = m.get("weekly_labels", [])
        weekly_vals = m.get("weekly_calculated_values", [])
        if weekly_labels and weekly_vals:
            weekly_df = pd.DataFrame({
                "Weekly Range Level": weekly_labels,
                "Calculated Value": [fmt(v) for v in weekly_vals],
            })
            st.table(weekly_df)
        else:
            st.warning(
                "⚠️ Weekly zones were not calculated in the active dataset. Please"
                " re-fetch or upload with 'Enable Weekly Zone Calculation' checked."
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
