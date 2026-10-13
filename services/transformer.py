import io
from openpyxl.styles import Font
import pandas as pd


class DataTransformer:

    def __init__(self, metrics):
        self.m = metrics

    def build_summary_dataframe(self):
        summary_data = {
            'Metrics': [
                'At-The-Money Strike (ATM)',
                'ATM Call Close Value',
                'ATM Call High Value',
                'ATM Call Low Value',
                'ATM Call Status',
                'ATM Put Close Value',
                'ATM Put High Value',
                'ATM Put Low Value',
                'ATM Put Status',
                'Total Close Value (Straddle Premium)',
                'Total Time Value',
                '  ',
                'Maximum Resistance',
                'Minimum Resistance',
                'Change in PDC',
                'Previous Day Close (PDC CAS)',
                'Minimum Support',
                'Maximum Support',
            ],
            'Value': [
                self.m['atm_strike'],
                self.m['atm_ce_close'],
                self.m['atm_ce_high'],
                self.m['atm_ce_low'],
                self.m['atm_ce_status'],
                self.m['atm_pe_close'],
                self.m['atm_pe_high'],
                self.m['atm_pe_low'],
                self.m['atm_pe_status'],
                self.m['total_close_value'],
                self.m['total_time_value'],
                None,
                self.m['max_resistance'],
                self.m['min_resistance'],
                self.m['change_in_pdc_val'],
                self.m['nifty_close'],
                self.m['min_support'],
                self.m['max_support'],
            ],
            'Expiry Date': [
                self.m['formatted_expiry_str'] if i == 0 else None for i in range(18)
            ],
        }
        summary_df = pd.DataFrame(summary_data)

        total_summary_rows = len(summary_df)
        blank_col = [None] * total_summary_rows
        padded_weekly_labels = self.m['weekly_labels'] + [None] * (
                total_summary_rows - len(self.m['weekly_labels'])
        )
        padded_weekly_values = self.m['weekly_calculated_values'] + [None] * (
                total_summary_rows - len(self.m['weekly_calculated_values'])
        )

        summary_df[' '] = blank_col
        summary_df['Weekly range'] = padded_weekly_labels
        summary_df['Metrics '] = padded_weekly_values

        # Sniper rows
        sniper_output = [
            [
                f"ATM strike price - {self.m['final_sniper_atm']} CE",
                f"OTM strike price - {self.m['final_sniper_atm'] - 100} PE",
            ],
            [
                f"high - {self.m['ce_block_atm']['CE_HIGH']}",
                f"high - {self.m['ce_block_otm']['PE_HIGH']}",
            ],
            [
                f"close - {self.m['ce_block_atm']['CE_CLOSE']}",
                f"close - {self.m['ce_block_otm']['PE_CLOSE']}",
            ],
            [f"sniper - {self.m['final_sniper_calculation']}", ""],
            [
                f"ATM strike price - {self.m['final_sniper_atm']} PE",
                f"OTM strike price - {self.m['final_sniper_atm'] + 100} CE",
            ],
            [
                f"high - {self.m['pe_block_atm']['PE_HIGH']}",
                f"high - {self.m['pe_block_otm']['CE_HIGH']}",
            ],
            [
                f"close - {self.m['pe_block_atm']['PE_CLOSE']}",
                f"close - {self.m['pe_block_otm']['CE_CLOSE']}",
            ],
            [f"sniper - {self.m['final_sniper_calculation']}", ""],
        ]

        sniper_append_rows = [
            {"Metrics": item[0], "Value": item[1], "Expiry Date": None}
            for item in sniper_output
        ]
        sniper_append_df = pd.DataFrame(sniper_append_rows)

        blank_row = pd.DataFrame(
            [{"Metrics": " ", "Value": None, "Expiry Date": None}]
        )
        extended_summary_df = pd.concat(
            [summary_df, blank_row, blank_row, sniper_append_df], ignore_index=True
        )
        return extended_summary_df

    def generate_excel_bytes(self):
        df = self.build_summary_dataframe()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Strategy_Summary", index=False)
            worksheet = writer.sheets["Strategy_Summary"]

            # Apply conditional strikethrough for Previous Day Close (PDC CAS) if Change in PDC is active
            if self.m.get("change_in_pdc_val", "---") != "---":
                for row_idx, cell in enumerate(worksheet["A"], start=1):
                    if cell.value == "Previous Day Close (PDC CAS)":
                        val_cell = worksheet.cell(row=row_idx, column=2)
                        val_cell.font = Font(strike=True)
                        break

            for col in worksheet.columns:
                max_len = max(
                    (len(str(cell.value)) for cell in col if cell.value is not None),
                    default=0,
                )
                col_letter = col[0].column_letter
                worksheet.column_dimensions[col_letter].width = max(max_len + 3, 15)
        return output.getvalue()