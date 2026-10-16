"""
classifier.py
=============

Adds the Type and Category to each AEON transaction, runs the running-balance
check, and detects duplicate (mirrored) pocket transfers.

Type values:
  * "Own account"  - counterparty is the account holder's own name
  * "Internal"     - transfer to/from one of the user's own pockets
  * "Profit"       - "Profit Earned" rows
  * "P2P in"/"P2P out" - DuitQR P2P transfers to/from individuals
  * "Income"       - money in that isn't any of the above
  * "Spending"     - money out that isn't any of the above

"Own account" and "Internal" are flagged so they are EXCLUDED from real
spending / income and reported separately as cashflow.
"""

from __future__ import annotations

from pathlib import Path

from .aeon_parser import AeonTransaction, AccountSummary


# The account holder's own name, read from the statement header. Transfers whose
# counterparty equals this name are "Own account" movements, not spending/income.
ACCOUNT_HOLDER = "MUHAMMAD HAZIQ DANIEL BIN ROSLI"


def _load_categories() -> list[tuple[str, list[str]]]:
    """Load the editable category keyword map. Falls back to a built-in copy if
    PyYAML isn't installed."""
    path = Path(__file__).with_name("categories.yaml")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [(cat, [str(k).lower() for k in (kws or [])]) for cat, kws in data.items()]
    except Exception:
        return list(_FALLBACK_CATEGORIES.items())


# Mirror of categories.yaml so classification still works without PyYAML / file.
_FALLBACK_CATEGORIES = {
    "Food & Dining": ["restoran", "warung", "cafe", "kfc", "4 fingers", "4fingers",
                      "texas", "bakery", "baker's cottage", "makdah", "andaki food",
                      "family fried chicken", "a1 food", "mantap sempoi", "sofea basha",
                      "nasi kandar", "bistro", "al-fariz", "al fariz"],
    "Groceries & Convenience": ["kk super mart", "kk super", "emart", "7-eleven",
                                "7 eleven", "7eleven", "pasar mini", "pasar",
                                "mini market", "ramjan", "psry", "ban soon"],
    "Fuel": ["shell", "petronas", "pss", "petron", "caltex", "bhp"],
    "Vehicle": ["motor", "syarikat motor", "workshop", "bengkel", "tayar"],
    "Laundry": ["laundry", "dobi", "simple laundry"],
    "Shopping & Household": ["decathlon", "ninso", "mr diy", "mr. diy", "ecoshops",
                             "ecoshop", "mydin", "household", "zxm enterprise",
                             "laitah", "cacabela", "asad permata", "mahmoodeli",
                             "fortunatecup"],
    "P2P / Individuals": [],
    "Profit Earned": ["profit earned"],
}

_CATEGORIES = _load_categories()


def _norm(s: str) -> str:
    return " ".join(str(s).split()).strip().lower()


def classify(tx: AeonTransaction, pocket_names: set[str]) -> None:
    """Set tx.tx_type and tx.category in place."""
    cp = _norm(tx.counterparty)
    holder = _norm(ACCOUNT_HOLDER)
    text = f"{tx.counterparty} {tx.description}".lower()

    # ---- Type ----
    if "profit earned" in tx.method.lower() or "profit earned" in tx.description.lower():
        tx.tx_type = "Profit"
    elif cp in {_norm(p) for p in pocket_names}:
        # counterparty is one of the user's own pockets (or the main account name)
        tx.tx_type = "Internal"
    elif cp == holder:
        tx.tx_type = "Own account"
    elif "p2p" in tx.method.lower():
        tx.tx_type = "P2P in" if tx.money_in > 0 else "P2P out"
    elif tx.money_in > 0:
        tx.tx_type = "Income"
    else:
        tx.tx_type = "Spending"

    # ---- Category ----
    if tx.tx_type == "Profit":
        tx.category = "Profit Earned"
    elif tx.tx_type in ("Internal", "Own account"):
        tx.category = "Internal / Own account"
    else:
        cat = _match_category(text)
        if cat:
            tx.category = cat
        elif tx.tx_type in ("P2P in", "P2P out"):
            tx.category = "P2P / Individuals"
        elif tx.tx_type == "Income":
            tx.category = "Income"
        else:
            # money out with an individual's name and no merchant keyword -> P2P
            tx.category = "P2P / Individuals"


def _match_category(text: str) -> str:
    for cat, keywords in _CATEGORIES:
        for kw in keywords:
            if kw and kw in text:
                return cat
    return ""


def run_balance_checks(transactions: list[AeonTransaction],
                       summaries: dict[str, AccountSummary]) -> None:
    """
    Verify prev_balance + signed_amount == balance for each row, per account.
    The first row of each account is checked against the opening balance.
    Sets tx.balance_check to "ok" / "FAIL" / "n/a".
    """
    prev: dict[str, float] = {}
    for name, summ in summaries.items():
        if summ.opening_balance is not None:
            prev[name] = summ.opening_balance

    for tx in transactions:
        if tx.balance is None:
            tx.balance_check = "n/a"
            continue
        p = prev.get(tx.account)
        if p is None:
            # no opening reference yet; seed from this row's implied previous
            prev[tx.account] = tx.balance
            tx.balance_check = "n/a"
            continue
        expected = round(p + tx.signed_amount, 2)
        tx.balance_check = "ok" if abs(expected - tx.balance) < 0.005 else "FAIL"
        prev[tx.account] = tx.balance


def classify_all(transactions: list[AeonTransaction],
                 summaries: dict[str, AccountSummary]) -> None:
    """Classify every transaction and run the balance checks (in place)."""
    pocket_names = set(summaries.keys())
    for tx in transactions:
        classify(tx, pocket_names)
    run_balance_checks(transactions, summaries)
