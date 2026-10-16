"""
exporter.py
===========

Writes all the analysis into a single, nicely formatted Excel workbook with
one sheet per view and a couple of charts.

Sheets produced:
  1. Overview            - headline numbers
  2. Clean Transactions  - every transaction, sorted by date
  3. Daily Summary       - spend per day (+ line chart)
  4. Monthly Summary     - spend per month
  5. Category Breakdown  - where money goes (+ pie chart)
  6. Top Payees          - who you pay the most
  7. Budget Forecast     - next-month projection
  8. Category Forecast   - projected spend per category
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import analyzer


_MONEY_FMT = "#,##0.00"
_HEADER_BG = "#305496"


def export_to_excel(df: pd.DataFrame, out_path: str | Path) -> Path:
    """Build the full workbook from the clean transaction DataFrame."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    daily = analyzer.daily_summary(df)
    monthly = analyzer.monthly_summary(df)
    cats = analyzer.category_breakdown(df)
    payees = analyzer.top_payees(df)
    forecast = analyzer.budget_forecast(df)
    cat_forecast = analyzer.category_forecast(df)
    overview = analyzer.build_overview(df)

    with pd.ExcelWriter(out_path, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        wb = writer.book
        money = wb.add_format({"num_format": _MONEY_FMT})
        header_fmt = wb.add_format(
            {"bold": True, "bg_color": _HEADER_BG, "font_color": "white",
             "border": 1, "align": "center", "valign": "vcenter"}
        )
        title_fmt = wb.add_format({"bold": True, "font_size": 14})
        label_fmt = wb.add_format({"bold": True})

        # ---- Overview sheet ----
        ov = writer.book.add_worksheet("Overview")
        writer.sheets["Overview"] = ov
        ov.write("A1", "Bank Statement Summary", title_fmt)
        ov.write("A2", f"Generated {datetime.now():%Y-%m-%d %H:%M}")
        pairs = [
            ("Transactions", overview["transactions"]),
            ("Date range", f'{overview["first_date"]} to {overview["last_date"]}'
                           if overview["first_date"] else "-"),
            ("Days covered", overview["days"]),
            ("Total money in", overview["money_in"]),
            ("Total money out", overview["money_out"]),
            ("Net (in - out)", overview["net"]),
        ]
        for i, (label, value) in enumerate(pairs, start=4):
            ov.write(f"A{i}", label, label_fmt)
            if isinstance(value, float):
                ov.write_number(f"B{i}", value, money)
            else:
                ov.write(f"B{i}", value)
        ov.set_column("A:A", 24)
        ov.set_column("B:B", 28)

        # ---- Clean Transactions ----
        _write_df(writer, df, "Clean Transactions", header_fmt, money,
                  money_cols=["Money In", "Money Out", "Balance"])

        # ---- Daily Summary (+ chart) ----
        _write_df(writer, daily, "Daily Summary", header_fmt, money,
                  money_cols=["Money In", "Money Out", "Net"])
        if not daily.empty:
            _add_daily_chart(writer, daily)

        # ---- Monthly Summary ----
        _write_df(writer, monthly, "Monthly Summary", header_fmt, money,
                  money_cols=["Money In", "Money Out", "Net"])

        # ---- Category Breakdown (+ pie) ----
        _write_df(writer, cats, "Category Breakdown", header_fmt, money,
                  money_cols=["Total Spent"])
        if not cats.empty:
            _add_category_pie(writer, cats)

        # ---- Top Payees ----
        _write_df(writer, payees, "Top Payees", header_fmt, money,
                  money_cols=["Total Sent"])

        # ---- Budget Forecast ----
        _write_df(writer, forecast, "Budget Forecast", header_fmt, money, money_cols=[])

        # ---- Category Forecast ----
        _write_df(writer, cat_forecast, "Category Forecast", header_fmt, money,
                  money_cols=["Spent (data period)", "Avg per day", "Projected next month"])

    return out_path


def _write_df(writer, df: pd.DataFrame, sheet: str, header_fmt, money_fmt, money_cols):
    """Write a DataFrame with a styled header, auto column widths and money formatting."""
    if df is None or df.empty:
        ws = writer.book.add_worksheet(sheet)
        writer.sheets[sheet] = ws
        ws.write("A1", "No data available for this view.")
        return

    df.to_excel(writer, sheet_name=sheet, index=False, startrow=0)
    ws = writer.sheets[sheet]

    for col_idx, col in enumerate(df.columns):
        ws.write(0, col_idx, col, header_fmt)
        # width based on content
        series = df[col].astype(str)
        width = max(len(str(col)), int(series.map(len).max()) if len(series) else 10) + 2
        width = min(max(width, 10), 50)
        if col in money_cols:
            ws.set_column(col_idx, col_idx, width, money_fmt)
        else:
            ws.set_column(col_idx, col_idx, width)

    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, len(df), len(df.columns) - 1)


def _add_daily_chart(writer, daily: pd.DataFrame):
    wb = writer.book
    ws = writer.sheets["Daily Summary"]
    n = len(daily)
    chart = wb.add_chart({"type": "line"})
    # Money Out column index
    cols = list(daily.columns)
    out_idx = cols.index("Money Out")
    in_idx = cols.index("Money In")
    day_idx = cols.index("Day")
    chart.add_series({
        "name": "Money Out",
        "categories": ["Daily Summary", 1, day_idx, n, day_idx],
        "values": ["Daily Summary", 1, out_idx, n, out_idx],
        "line": {"color": "#C0392B"},
    })
    chart.add_series({
        "name": "Money In",
        "categories": ["Daily Summary", 1, day_idx, n, day_idx],
        "values": ["Daily Summary", 1, in_idx, n, in_idx],
        "line": {"color": "#27AE60"},
    })
    chart.set_title({"name": "Daily Spend Trend"})
    chart.set_x_axis({"name": "Day"})
    chart.set_y_axis({"name": "Amount"})
    chart.set_size({"width": 720, "height": 360})
    ws.insert_chart(1, len(cols) + 1, chart)


def _add_category_pie(writer, cats: pd.DataFrame):
    wb = writer.book
    ws = writer.sheets["Category Breakdown"]
    n = len(cats)
    cols = list(cats.columns)
    cat_idx = cols.index("Category")
    spent_idx = cols.index("Total Spent")
    chart = wb.add_chart({"type": "pie"})
    chart.add_series({
        "name": "Spend by Category",
        "categories": ["Category Breakdown", 1, cat_idx, n, cat_idx],
        "values": ["Category Breakdown", 1, spent_idx, n, spent_idx],
        "data_labels": {"percentage": True},
    })
    chart.set_title({"name": "Where Your Money Goes"})
    chart.set_size({"width": 520, "height": 360})
    ws.insert_chart(1, len(cols) + 1, chart)


def export_to_csv(df: pd.DataFrame, out_path: str | Path) -> Path:
    """Also offer a plain CSV of the clean transactions."""
    out_path = Path(out_path)
    df.to_csv(out_path, index=False)
    return out_path
