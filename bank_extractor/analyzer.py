"""
analyzer.py
===========

Turns a list of Transactions into the summaries you actually care about:

  * clean transaction table (sorted by date, with category + running balance)
  * daily spend summary        -> how much went out / came in each day
  * monthly summary            -> totals per month
  * category breakdown         -> where the money goes
  * top payees                 -> who you send the most money to
  * budget forecast            -> projected spend for next month

Everything is returned as pandas DataFrames so the exporter can drop them
straight into Excel sheets.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .categorizer import categorize
from .parser import Transaction


def transactions_to_dataframe(transactions: list[Transaction]) -> pd.DataFrame:
    """Build the master clean-data table."""
    rows = []
    for t in transactions:
        rows.append(
            {
                "Date": t.date,
                "Description": t.description,
                "Party (Who)": t.party,
                "Category": categorize(t.description, t.party, t.direction),
                "Direction": "Money In" if t.direction == "in" else "Money Out",
                "Money In": t.amount if t.direction == "in" else 0.0,
                "Money Out": t.amount if t.direction == "out" else 0.0,
                "Balance": t.balance,
                "Source File": t.source_file,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["Date", "Description"]).reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Total money in / out and net per day, plus number of transactions."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(df["Date"].dt.date).agg(
        Transactions=("Description", "count"),
        **{
            "Money In": ("Money In", "sum"),
            "Money Out": ("Money Out", "sum"),
        },
    )
    g["Net"] = g["Money In"] - g["Money Out"]
    g = g.reset_index().rename(columns={"Date": "Day"})
    g["Day"] = pd.to_datetime(g["Day"])
    return g.sort_values("Day").reset_index(drop=True)


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Total money in / out and net per calendar month."""
    if df.empty:
        return pd.DataFrame()
    month = df["Date"].dt.to_period("M").astype(str)
    g = df.groupby(month).agg(
        Transactions=("Description", "count"),
        **{
            "Money In": ("Money In", "sum"),
            "Money Out": ("Money Out", "sum"),
        },
    )
    g["Net"] = g["Money In"] - g["Money Out"]
    g = g.reset_index().rename(columns={"Date": "Month"})
    return g.sort_values("Month").reset_index(drop=True)


def category_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """How much was spent (money out) per category."""
    if df.empty:
        return pd.DataFrame()
    spend = df[df["Money Out"] > 0]
    if spend.empty:
        return pd.DataFrame()
    g = spend.groupby("Category").agg(
        Transactions=("Description", "count"),
        **{"Total Spent": ("Money Out", "sum")},
    ).reset_index()
    total = g["Total Spent"].sum()
    g["% of Spend"] = (g["Total Spent"] / total * 100).round(1) if total else 0
    return g.sort_values("Total Spent", ascending=False).reset_index(drop=True)


def top_payees(df: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    """Who you send the most money to (money out), aggregated by party."""
    if df.empty:
        return pd.DataFrame()
    spend = df[(df["Money Out"] > 0) & (df["Party (Who)"].astype(str).str.len() > 0)]
    if spend.empty:
        return pd.DataFrame()
    g = spend.groupby("Party (Who)").agg(
        Transactions=("Description", "count"),
        **{"Total Sent": ("Money Out", "sum")},
    ).reset_index()
    return g.sort_values("Total Sent", ascending=False).head(limit).reset_index(drop=True)


def budget_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simple, explainable forecast for next month:
      * average monthly spend across the months we have data for
      * average daily spend * 30
      * per-category projection based on category share of spend

    Returns a tidy table you can read at a glance.
    """
    if df.empty:
        return pd.DataFrame()

    monthly = monthly_summary(df)
    spend_total = df["Money Out"].sum()
    income_total = df["Money In"].sum()

    # span of days covered by the data
    days = (df["Date"].max() - df["Date"].min()).days + 1
    days = max(days, 1)
    avg_daily_spend = spend_total / days

    rows = []
    if not monthly.empty:
        avg_monthly_spend = monthly["Money Out"].mean()
        avg_monthly_income = monthly["Money In"].mean()
        rows.append(("Months of data", f"{len(monthly)}"))
        rows.append(("Average monthly income", round(avg_monthly_income, 2)))
        rows.append(("Average monthly spend", round(avg_monthly_spend, 2)))
        rows.append(("Average monthly net (savings)", round(avg_monthly_income - avg_monthly_spend, 2)))

    rows.append(("Average daily spend", round(avg_daily_spend, 2)))
    rows.append(("Projected spend next month (daily x 30)", round(avg_daily_spend * 30, 2)))
    rows.append(("Total income (all data)", round(income_total, 2)))
    rows.append(("Total spend (all data)", round(spend_total, 2)))

    forecast = pd.DataFrame(rows, columns=["Metric", "Value"])
    return forecast


def category_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """Projected spend per category for next month, based on daily averages."""
    if df.empty:
        return pd.DataFrame()
    spend = df[df["Money Out"] > 0]
    if spend.empty:
        return pd.DataFrame()
    days = (df["Date"].max() - df["Date"].min()).days + 1
    days = max(days, 1)
    g = spend.groupby("Category")["Money Out"].sum().reset_index()
    g["Avg per day"] = (g["Money Out"] / days).round(2)
    g["Projected next month"] = (g["Avg per day"] * 30).round(2)
    g = g.rename(columns={"Money Out": "Spent (data period)"})
    return g.sort_values("Projected next month", ascending=False).reset_index(drop=True)


def build_overview(df: pd.DataFrame) -> dict:
    """Headline numbers for the GUI dashboard."""
    if df.empty:
        return {
            "transactions": 0, "money_in": 0.0, "money_out": 0.0, "net": 0.0,
            "first_date": None, "last_date": None, "days": 0,
        }
    money_in = float(df["Money In"].sum())
    money_out = float(df["Money Out"].sum())
    return {
        "transactions": int(len(df)),
        "money_in": round(money_in, 2),
        "money_out": round(money_out, 2),
        "net": round(money_in - money_out, 2),
        "first_date": df["Date"].min().date(),
        "last_date": df["Date"].max().date(),
        "days": int((df["Date"].max() - df["Date"].min()).days + 1),
    }
