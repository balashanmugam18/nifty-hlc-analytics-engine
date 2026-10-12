from datetime import datetime, timedelta
import io
import math
import re
import zipfile
import pandas as pd


class NiftyCalculatorEngine:

  def __init__(
      self, uploaded_file_bytes, enable_weekly_zone=False, pdc_threshold=50
  ):
    self.uploaded_file_bytes = uploaded_file_bytes
    self.enable_weekly_zone = enable_weekly_zone
    self.pdc_threshold = pdc_threshold

  def process_bhavcopy(self):
    # Step 1 & 2: Open ZIP from memory bytes
    try:
      with zipfile.ZipFile(
          io.BytesIO(self.uploaded_file_bytes), 'r'
      ) as z:
        csv_file_name = z.namelist()[0]

        # Extract 8-digit date from filename
        date_match = re.search(r'(\d{8})', csv_file_name)
        if date_match:
          raw_date_str = date_match.group(1)
          file_trade_date = datetime.strptime(raw_date_str, '%Y%m%d')

          # Calculate next working day
          output_target_date = file_trade_date + timedelta(days=1)
          while output_target_date.weekday() >= 5:
            output_target_date += timedelta(days=1)
          formatted_out_date = output_target_date.strftime('%Y%m%d')
        else:
          formatted_out_date = datetime.now().strftime('%Y%m%d')
          file_trade_date = datetime.now()

        output_filename = f'Nifty_ATM_Analysis_{formatted_out_date}.xlsx'

        # Check delimiter structure
        preview_df = pd.read_csv(
            z.open(csv_file_name), sep='|', nrows=2, engine='python'
        )
        if len(preview_df.columns) <= 1:
          df = pd.read_csv(z.open(csv_file_name), sep=',', engine='python')
        else:
          df = pd.read_csv(z.open(csv_file_name), sep='|', engine='python')
    except Exception as e:
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

    # Step 3: Validate Nifty
    nifty_mask = df[col_mapping['Symbol']].str.upper() == 'NIFTY'
    if not nifty_mask.any():
      raise ValueError("No data found for 'NIFTY' symbol in the uploaded file.")

    # Step 4: Expiry filter
    options_mask = df[col_mapping['OptType']].isin(['CE', 'PE'])
    df_options = df[nifty_mask & options_mask].copy()

    df_options['Parsed_Expiry'] = pd.to_datetime(
        df_options[col_mapping['Expiry']], format='%Y-%m-%d', errors='coerce'
    )
    df_options = df_options.dropna(subset=['Parsed_Expiry'])

    trade_date_ts = pd.Timestamp(file_trade_date.date())
    df_options = df_options[df_options['Parsed_Expiry'] > trade_date_ts]

    if df_options.empty:
      raise ValueError('No valid future expiry dates found.')

    closest_expiry = df_options['Parsed_Expiry'].min()
    df_filtered = df_options[df_options['Parsed_Expiry'] == closest_expiry]
    formatted_expiry_str = closest_expiry.strftime('%d-%m-%Y')

    # Step 5: Merge CE & PE side-by-side
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

    # Step 6: ATM Core Metrics
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

    min_resistance = atm_strike + atm_ce_close
    min_support = atm_strike - atm_pe_close
    total_close_value = atm_ce_close + atm_pe_close
    max_resistance = atm_strike + total_close_value
    max_support = atm_strike - total_close_value

    # 📌 Added Total Time Value Calculation
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

    # Step 7: Weekly Zone
    weekly_labels = [
        'Maximum Resistance',
        'Minimum Resistance',
        'Previous Day Close (PDC)',
        'Minimum Support',
        'Maximum Support',
    ]
    if self.enable_weekly_zone:
      weekly_atm_1 = math.floor(nifty_close / 100.0) * 100
      weekly_atm_2 = (
          weekly_atm_1 + 100
          if nifty_close % 100 == 0
          else math.ceil(nifty_close / 100.0) * 100
      )

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
      weekly_calculated_values = [
          line2 + atm_2_straddle,
          line1,
          nifty_close,
          line2,
          line1 - atm_1_straddle,
      ]
    else:
      weekly_calculated_values = [None] * len(weekly_labels)

    # Step 8: Sniper Strategy
    sniper_atm_base = int(round(nifty_close / 100.0) * 100)

    def fetch_row_metrics(strike_price):
      match = final_df[final_df['STRIKE_PRICE'] == strike_price]
      if match.empty:
        return {'CE_CLOSE': 0.0, 'CE_HIGH': 0.0, 'PE_CLOSE': 0.0, 'PE_HIGH': 0.0}
      return {
          'CE_CLOSE': float(match['CE_CLOSE_VALUE'].iloc[0]),
          'CE_HIGH': float(match['CE_HIGH_VALUE'].iloc[0]),
          'PE_CLOSE': float(match['PE_CLOSE_VALUE'].iloc[0]),
          'PE_HIGH': float(match['PE_HIGH_VALUE'].iloc[0]),
      }

    def check_strike_validity(strike, threshold=30.0):
      otm_pe_metrics = fetch_row_metrics(strike - 100)
      otm_ce_metrics = fetch_row_metrics(strike + 100)
      sniper_val = (
          otm_pe_metrics['PE_CLOSE'] + otm_ce_metrics['CE_CLOSE']
      ) / 2.0
      atm_metrics = fetch_row_metrics(strike)
      ce_diff = atm_metrics['CE_CLOSE'] - sniper_val
      pe_diff = atm_metrics['PE_CLOSE'] - sniper_val
      return (
          (ce_diff >= threshold) and (pe_diff >= threshold),
          sniper_val,
          ce_diff,
          pe_diff,
      )

    current_atm = sniper_atm_base
    THRESHOLD = 30.0
    valid_strike_found = False
    final_sniper_atm = sniper_atm_base

    for _ in range(3):
      is_valid, _, ce_diff, pe_diff = check_strike_validity(
          current_atm, THRESHOLD
      )
      if is_valid:
        final_sniper_atm = current_atm
        valid_strike_found = True
        break
      current_atm = current_atm - 100 if ce_diff < pe_diff else current_atm + 100

    if not valid_strike_found:
      for candidate in [
          sniper_atm_base + 50,
          sniper_atm_base - 50,
          sniper_atm_base + 150,
          sniper_atm_base - 150,
      ]:
        is_valid, _, _, _ = check_strike_validity(candidate, THRESHOLD)
        if is_valid:
          final_sniper_atm = candidate
          valid_strike_found = True
          break
      if not valid_strike_found:
        final_sniper_atm = sniper_atm_base + 50

    ce_block_atm = fetch_row_metrics(final_sniper_atm)
    ce_block_otm = fetch_row_metrics(final_sniper_atm - 100)
    pe_block_atm = fetch_row_metrics(final_sniper_atm)
    pe_block_otm = fetch_row_metrics(final_sniper_atm + 100)
    final_sniper_calculation = (
        ce_block_otm['PE_CLOSE'] + pe_block_otm['CE_CLOSE']
    ) / 2.0

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
        'ce_block_atm': ce_block_atm,
        'ce_block_otm': ce_block_otm,
        'pe_block_atm': pe_block_atm,
        'pe_block_otm': pe_block_otm,
    }