"""
report.py
=========

Builds the final report data from classified AEON transactions:

  * per-account reconciliation (opening + in - out == closing, checked against
    the bank's printed Account summary)  -> PASS / FAIL
  * real spending / real income (excluding Internal + Own-account)
  * net own-account and net internal movement
  * By-Category totals (spending only)

The three DataFrames returned map 1:1 to the Overview / Transactions /
By Category sheets written by exporter_aeon.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from .aeon_parser import AeonTransaction, AccountSummary

# pandas is only needed for the *_dataframe() helpers used by the Excel exporter.
# Import lazily so the analysis/reconciliation logic works without pandas.


EXCLUDED_FROM_SPENDING = {"Internal", "Own account"}


@dataclass
class AccountRecon:
    account: str
    opening: float
    total_in: float
    total_out: float
    closing_computed: float
    closing_printed: float | None
    withdrawal_printed: float | None
    deposit_printed: float | None
    status: str  # PASS / FAIL


def reconcile_accounts(transactions: list[AeonTransaction],
                       summaries: dict[str, AccountSummary]) -> list[AccountRecon]:
    recons: list[AccountRecon] = []
    for name, summ in summaries.items():
        rows = [t for t in transactions if t.account == name]
        total_in = round(sum(t.money_in for t in rows), 2)
        total_out = round(sum(t.money_out for t in rows), 2)
        opening = summ.opening_balance if summ.opening_balance is not None else 0.0
        closing_computed = round(opening + total_in - total_out, 2)

        checks = []
        if summ.closing_balance is not None:
            checks.append(abs(closing_computed - summ.closing_balance) < 0.005)
        if summ.total_withdrawal is not None:
            checks.append(abs(total_out - summ.total_withdrawal) < 0.005)
        if summ.total_deposits is not None:
            checks.append(abs(total_in - summ.total_deposits) < 0.005)
        all_rows_ok = all(t.balance_check in ("ok", "n/a") for t in rows)
        checks.append(all_rows_ok)

        status = "PASS" if checks and all(checks) else "FAIL"
        recons.append(AccountRecon(
            account=name, opening=round(opening, 2), total_in=total_in,
            total_out=total_out, closing_computed=closing_computed,
            closing_printed=summ.closing_balance,
            withdrawal_printed=summ.total_withdrawal,
            deposit_printed=summ.total_deposits, status=status,
        ))
    return recons


def cashflow_summary(transactions: list[AeonTransaction]) -> dict:
    """Headline numbers that separate real money from internal shuffling."""
    real_spend = round(sum(t.money_out for t in transactions
                           if t.tx_type not in EXCLUDED_FROM_SPENDING), 2)
    real_income = round(sum(t.money_in for t in transactions
                            if t.tx_type not in EXCLUDED_FROM_SPENDING), 2)

    own_out = round(sum(t.money_out for t in transactions if t.tx_type == "Own account"), 2)
    own_in = round(sum(t.money_in for t in transactions if t.tx_type == "Own account"), 2)
    int_out = round(sum(t.money_out for t in transactions if t.tx_type == "Internal"), 2)
    int_in = round(sum(t.money_in for t in transactions if t.tx_type == "Internal"), 2)

    return {
        "real_spending": real_spend,
        "real_income": real_income,
        "own_account_out": own_out,
        "own_account_in": own_in,
        "own_account_net": round(own_in - own_out, 2),
        "internal_out": int_out,
        "internal_in": int_in,
        "internal_net": round(int_in - int_out, 2),
    }


# --------------------------------------------------------------------------- #
# DataFrames for export
# --------------------------------------------------------------------------- #
def transactions_dataframe(transactions: list[AeonTransaction]):
    import pandas as pd
    rows = []
    for t in transactions:
        rows.append({
            "Date": t.posting_date,
            "Transaction Date": t.transaction_date or "",
            "Account": t.account,
            "Description": t.description,
            "Counterparty": t.counterparty,
            "Method": t.method,
            "Money In": t.money_in,
            "Money Out": t.money_out,
            "Balance": t.balance,
            "Type": t.tx_type,
            "Category": t.category,
            "Source page": t.source_page,
            "Balance check": t.balance_check,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Account", "Date"], kind="stable").reset_index(drop=True)
    return df


def overview_dataframe(recons: list[AccountRecon], cash: dict):
    import pandas as pd
    rows = []
    for r in recons:
        rows.append({
            "Account": r.account,
            "Opening": r.opening,
            "Total In": r.total_in,
            "Total Out": r.total_out,
            "Closing (computed)": r.closing_computed,
            "Closing (bank)": r.closing_printed if r.closing_printed is not None else "",
            "Reconciliation": r.status,
        })
    df = pd.DataFrame(rows)
    return df


def cashflow_dataframe(cash: dict):
    import pandas as pd
    rows = [
        ("Real spending (excl. internal & own-account)", cash["real_spending"]),
        ("Real income (excl. internal & own-account)", cash["real_income"]),
        ("Own-account transfers out", cash["own_account_out"]),
        ("Own-account transfers in", cash["own_account_in"]),
        ("Own-account net movement", cash["own_account_net"]),
        ("Internal (pocket) transfers out", cash["internal_out"]),
        ("Internal (pocket) transfers in", cash["internal_in"]),
        ("Internal net movement", cash["internal_net"]),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Amount"])


def by_category_dataframe(transactions: list[AeonTransaction]):
    import pandas as pd
    spend = [t for t in transactions
             if t.money_out > 0 and t.tx_type not in EXCLUDED_FROM_SPENDING]
    if not spend:
        return pd.DataFrame(columns=["Category", "Total", "Share %", "Count"])
    agg: dict[str, list] = {}
    for t in spend:
        c = t.category or "Uncategorized"
        a = agg.setdefault(c, [0.0, 0])
        a[0] += t.money_out
        a[1] += 1
    total = sum(v[0] for v in agg.values())
    rows = [{"Category": c, "Total": round(v[0], 2),
             "Share %": round(v[0] / total * 100, 1) if total else 0.0,
             "Count": v[1]}
            for c, v in agg.items()]
    df = pd.DataFrame(rows).sort_values("Total", ascending=False).reset_index(drop=True)
    return df
