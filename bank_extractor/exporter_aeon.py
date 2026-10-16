"""
exporter_aeon.py
================

Writes the AEON report into an .xlsx with three sheets:
  * Overview      - per-account recon (PASS/FAIL) + a cashflow block
  * Transactions  - the full clean transaction table
  * By Category   - spending totals, share %, count
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import report
from .aeon_parser import AeonTransaction, AccountSummary


_MONEY = "#,##0.00"
_HEADER_BG = "#C8102E"   # AEON red


def export(transactions: list[AeonTransaction],
           summaries: dict[str, AccountSummary],
           out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    recons = report.reconcile_accounts(transactions, summaries)
    cash = report.cashflow_summary(transactions)
    tx_df = report.transactions_dataframe(transactions)
    ov_df = report.overview_dataframe(recons, cash)
    cf_df = report.cashflow_dataframe(cash)
    cat_df = report.by_category_dataframe(transactions)

    with pd.ExcelWriter(out_path, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        wb = writer.book
        money = wb.add_format({"num_format": _MONEY})
        header = wb.add_format({"bold": True, "bg_color": _HEADER_BG,
                                "font_color": "white", "border": 1,
                                "align": "center", "valign": "vcenter"})
        title = wb.add_format({"bold": True, "font_size": 14})
        label = wb.add_format({"bold": True})
        pass_fmt = wb.add_format({"bold": True, "font_color": "#1E7B34"})
        fail_fmt = wb.add_format({"bold": True, "font_color": "#C0392B"})

        # ---------------- Overview ----------------
        ws = wb.add_worksheet("Overview")
        writer.sheets["Overview"] = ws
        ws.write("A1", "AEON e-Statement - Overview", title)
        ws.write("A2", f"Generated {datetime.now():%Y-%m-%d %H:%M}")

        start = 4
        headers = list(ov_df.columns)
        for c, h in enumerate(headers):
            ws.write(start, c, h, header)
        for r, (_, row) in enumerate(ov_df.iterrows(), start=start + 1):
            for c, h in enumerate(headers):
                val = row[h]
                if h == "Reconciliation":
                    ws.write(r, c, val, pass_fmt if val == "PASS" else fail_fmt)
                elif isinstance(val, (int, float)) and h not in ("Account",):
                    ws.write_number(r, c, float(val), money)
                else:
                    ws.write(r, c, val)
        ws.set_column(0, 0, 20)
        ws.set_column(1, len(headers) - 1, 16)

        # cashflow block below
        cf_start = start + len(ov_df) + 3
        ws.write(cf_start - 1, 0, "Cashflow (real money vs. internal shuffling)", label)
        ws.write(cf_start, 0, "Metric", header)
        ws.write(cf_start, 1, "Amount", header)
        for i, (_, row) in enumerate(cf_df.iterrows(), start=cf_start + 1):
            ws.write(i, 0, row["Metric"])
            ws.write_number(i, 1, float(row["Amount"]), money)
        ws.set_column(0, 0, 44)

        # ---------------- Transactions ----------------
        _write_table(writer, tx_df, "Transactions", header, money,
                     money_cols=["Money In", "Money Out", "Balance"])

        # ---------------- By Category ----------------
        _write_table(writer, cat_df, "By Category", header, money,
                     money_cols=["Total"])

    return out_path


def _write_table(writer, df: pd.DataFrame, sheet: str, header_fmt, money_fmt, money_cols):
    if df is None or df.empty:
        ws = writer.book.add_worksheet(sheet)
        writer.sheets[sheet] = ws
        ws.write("A1", "No data.")
        return
    df.to_excel(writer, sheet_name=sheet, index=False, startrow=0)
    ws = writer.sheets[sheet]
    for ci, col in enumerate(df.columns):
        ws.write(0, ci, col, header_fmt)
        series = df[col].astype(str)
        width = min(max(len(str(col)), int(series.map(len).max()) if len(series) else 10) + 2, 55)
        if col in money_cols:
            ws.set_column(ci, ci, width, money_fmt)
        else:
            ws.set_column(ci, ci, width)
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, len(df), len(df.columns) - 1)
