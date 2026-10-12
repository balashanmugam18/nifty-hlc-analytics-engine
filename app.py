from datetime import datetime, timedelta
import os
import pickle
import pandas as pd
import streamlit as st

from backend.calculator import NiftyCalculatorEngine
from services.transformer import DataTransformer

st.set_page_config(page_title="HLC Nifty Analysis Dashboard", layout="wide")

CACHE_FILE = "server_cache_metrics.pkl"


def save_to_server_cache(metrics, excel_bytes, file_name):
  data = {
      "metrics": metrics,
      "excel_bytes": excel_bytes,
      "file_name": file_name,
      "timestamp": datetime.now(),
  }
  with open(CACHE_FILE, "wb") as f:
    pickle.dump(data, f)


def load_from_server_cache():
  if os.path.exists(CACHE_FILE):
    try:
      with open(CACHE_FILE, "rb") as f:
        data = pickle.load(f)
        # Check 24-hour expiration globally
        if datetime.now() - data["timestamp"] > timedelta(hours=24):
          os.remove(CACHE_FILE)
          return None
        return data
    except Exception:
      return None
  return None


# ==============================================================================
# 1. VIEW PASSWORD GATEWAY (Page Access Control)
# ==============================================================================
def check_view_password():
  def password_entered():
    try:
      correct_pass = st.secrets.get("VIEW_PASSWORD", "view123")
    except Exception:
      correct_pass = "view123"

    if st.session_state["view_pass_input"] == correct_pass:
      st.session_state["view_authenticated"] = True
      del st.session_state["view_pass_input"]
    else:
      st.session_state["view_authenticated"] = False

  if st.session_state.get("view_authenticated", False):
    return True

  st.title("🔒 Restricted Access")
  st.text_input(
      "Enter View Password to Access Dashboard:",
      type="password",
      on_change=password_entered,
      key="view_pass_input",
  )

  if "view_authenticated" in st.session_state:
    st.error("❌ Incorrect View Password")

  return False


if not check_view_password():
  st.stop()


# ==============================================================================
# 2. MAIN APPLICATION CONTENT
# ==============================================================================
st.title("📊 HLC Nifty Calculation & Strategy Dashboard")

# Sidebar Configuration
st.sidebar.header("Configuration")
enable_weekly = st.sidebar.checkbox(
    "Enable Weekly Zone Calculation", value=False
)
pdc_thresh = st.sidebar.slider(
    "PDC Difference Threshold", min_value=25, max_value=150, value=50, step=25
)

# ==============================================================================
# 3. ADMIN UPLOAD SECTION
# ==============================================================================
st.markdown("---")
st.subheader("📂 Bhavcopy Data Upload (Admin Only)")

upload_pass_input = st.text_input(
    "Enter Upload Password to unlock file uploader:",
    type="password",
    key="upload_pass_input_main",
)

try:
  correct_upload_pass = st.secrets.get("UPLOAD_PASSWORD", "upload456")
except Exception:
  correct_upload_pass = "upload456"

if upload_pass_input != correct_upload_pass:
  if upload_pass_input != "":
    st.error("⛔ Incorrect Upload Password. File uploader remains locked.")
  else:
    st.info(
        "🔒 Enter the Upload Password above if you are Admin looking to upload a"
        " new file."
    )
else:
  st.success("🔓 Admin Upload Authorized!")
  uploaded_file = st.file_uploader(
      "Upload Bhav Copy ZIP File", type=["zip"], key="bhav_uploader"
  )

  if uploaded_file is not None:
    cached_data = load_from_server_cache()
    if cached_data is None or cached_data.get("file_name") != uploaded_file.name:
      try:
        with st.spinner("Processing Bhavcopy and saving to server..."):
          file_bytes = uploaded_file.read()
          engine = NiftyCalculatorEngine(
              file_bytes,
              enable_weekly_zone=enable_weekly,
              pdc_threshold=pdc_thresh,
          )
          metrics = engine.process_bhavcopy()

          transformer = DataTransformer(metrics)
          excel_bytes = transformer.generate_excel_bytes()

          # Save globally to disk cache
          save_to_server_cache(metrics, excel_bytes, uploaded_file.name)
          st.success(
              "Bhavcopy processed successfully and published globally!"
          )
          st.rerun()  # Refresh page to render dashboard immediately
      except Exception as e:
        st.error(f"Error processing file: {e}")

# ==============================================================================
# 4. DASHBOARD UI DISPLAY (Loads from Server Cache for ALL users)
# ==============================================================================
cached_data = load_from_server_cache()

if cached_data is None:
  st.info(
      "📌 **Waiting for Admin to upload Bhavcopy... Dashboard will appear"
      " here once processed.**"
  )
else:
  m = cached_data["metrics"]
  excel_bytes = cached_data["excel_bytes"]
  output_filename = m.get("output_filename", "Nifty_ATM_Analysis_20261012")

  # Extract date string from output_filename and format it strictly as DD/MM/YYYY
  try:
    clean_name = output_filename.split(".")[0]
    date_str_raw = clean_name.split("_")[-1]  # Grabs '20261012'
    formatted_date = datetime.strptime(date_str_raw, "%Y%m%d").strftime(
        "%d/%m/%Y"
    )
  except Exception:
    formatted_date = "N/A"

  # 📌 ACTIVE REPORT IDENTIFIER BANNER
  st.success(
      f"📊 **Active Analytics Report:** `{output_filename}`  \n🗓️ **Date:**"
      f" `{formatted_date}`"
  )

  st.markdown("---")

  # 1. KEY STRATEGY METRICS
  st.subheader("Key Strategy Metrics")
  key_metrics_df = pd.DataFrame({
      "Metric": [
          "Maximum Resistance",
          "Minimum Resistance",
          "Change in Previous Day Close (PDC)",
          "Previous Day Close (PDC CAS)",
          "Minimum Support",
          "Maximum Support",
          "Total Time Value",
      ],
      "Value": [
          m["max_resistance"],
          m["min_resistance"],
          m["change_in_pdc_val"],
          m["nifty_close"],
          m["min_support"],
          m["max_support"],
          m.get("total_time_value", 0.0),
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
          m["atm_strike"],
          m["atm_ce_close"],
          m["atm_ce_high"],
          m["atm_ce_low"],
          m["atm_ce_status"],
          m["atm_pe_close"],
          m["atm_pe_high"],
          m["atm_pe_low"],
          m["atm_pe_status"],
          m["total_close_value"],
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
    weekly_df = pd.DataFrame({
        "Weekly Range Level": m["weekly_labels"],
        "Calculated Value": m["weekly_calculated_values"],
    })
    st.table(weekly_df)
    st.markdown("---")

  # 4. SNIPER LEVELS METRICS
  st.subheader("SNIPER LEVELS METRICS")
  sniper_col1, sniper_col2 = st.columns(2)

  with sniper_col1:
    st.markdown(
        f"**ATM strike price - {m['final_sniper_atm']} CE** | "
        f" high - **{m['ce_block_atm']['CE_HIGH']}** | "
        f" close - **{m['ce_block_atm']['CE_CLOSE']}**"
    )
    st.markdown(f"**sniper - {m['final_sniper_calculation']}**")
    st.markdown(
        f"**ATM strike price - {m['final_sniper_atm']} PE** | "
        f" high - **{m['pe_block_atm']['PE_HIGH']}** | "
        f" close - **{m['pe_block_atm']['PE_CLOSE']}**"
    )
    st.markdown(f"**sniper - {m['final_sniper_calculation']}**")

  with sniper_col2:
    st.markdown(
        f"**OTM strike price - {m['final_sniper_atm'] - 100} PE** | "
        f" high - **{m['ce_block_otm']['PE_HIGH']}** | "
        f" close - **{m['ce_block_otm']['PE_CLOSE']}**"
    )
    st.write("")
    st.markdown(
        f"**OTM strike price - {m['final_sniper_atm'] + 100} CE** | "
        f" high - **{m['pe_block_otm']['CE_HIGH']}** | "
        f" close - **{m['pe_block_otm']['CE_CLOSE']}**"
    )

  st.markdown("---")

  # 5. EXCEL DOWNLOAD BUTTON
  st.subheader("📥 Download Prepared Excel")
  st.download_button(
      label="Download Excel Output",
      data=excel_bytes,
      file_name=m["output_filename"],
      mime=(
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      ),
  )