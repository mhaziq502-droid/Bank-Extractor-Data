"""
categorizer.py
==============

Assigns a spending category to each transaction based on keywords found in its
description or party. Keeps it simple and transparent so you can tweak the
keyword lists to match how your own statements read.
"""

from __future__ import annotations

import re

# category -> list of keywords (checked case-insensitively against description + party)
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Food & Dining": [
        "restaurant", "cafe", "coffee", "kopitiam", "mcdonald", "kfc", "starbucks",
        "food", "makan", "grabfood", "foodpanda", "mamak", "bakery", "pizza",
    ],
    "Groceries": [
        "grocery", "supermarket", "mart", "tesco", "aeon", "giant", "lotus",
        "mydin", "jaya grocer", "99 speedmart", "econsave", "nsk",
    ],
    "Transport": [
        "grab", "petrol", "shell", "petronas", "caltex", "bhp", "toll", "touch n go",
        "tng", "parking", "mrt", "lrt", "ktm", "rapid", "taxi", "flight", "airasia",
        "fuel",
    ],
    "Bills & Utilities": [
        "tnb", "electric", "water", "syabas", "air selangor", "unifi", "maxis",
        "celcom", "digi", "umobile", "astro", "indah water", "bill", "utility",
        "internet", "telco", "insurance", "takaful",
    ],
    "Shopping": [
        "shopee", "lazada", "zalora", "uniqlo", "h&m", "ikea", "store", "mall",
        "shop", "retail", "amazon", "watson", "guardian", "sephora",
    ],
    "Entertainment": [
        "netflix", "spotify", "youtube", "cinema", "gsc", "tgv", "game", "steam",
        "disney", "iflix", "concert", "movie",
    ],
    "Health": [
        "clinic", "hospital", "pharmacy", "farmasi", "doctor", "dental", "medical",
        "guardian", "caring",
    ],
    "Transfers": [
        "transfer", "trf", "duitnow", "ibg", "fpx", "instant", "giro", "to ",
        "kepada", "sent",
    ],
    "Cash & ATM": [
        "atm", "cash withdrawal", "withdrawal", "cdm", "cash deposit",
    ],
    "Income": [
        "salary", "gaji", "payroll", "dividend", "interest", "refund", "reimbursement",
        "bonus",
    ],
    "Fees & Charges": [
        "fee", "charge", "service charge", "stamp duty", "penalty", "gst", "sst",
        "commission",
    ],
}


def _compile(keywords: list[str]) -> re.Pattern:
    # word-boundary where it makes sense, substring otherwise
    parts = [re.escape(k) for k in keywords]
    return re.compile("|".join(parts), re.I)


_COMPILED = {cat: _compile(kw) for cat, kw in CATEGORY_KEYWORDS.items()}


def categorize(description: str, party: str = "", direction: str = "out") -> str:
    """Return a category label for a transaction."""
    text = f"{description} {party}".strip()
    if not text:
        return "Income" if direction == "in" else "Uncategorized"

    # money-in that looks like salary/refund -> Income
    if direction == "in":
        if _COMPILED["Income"].search(text):
            return "Income"

    for cat, pattern in _COMPILED.items():
        if cat == "Income" and direction == "out":
            continue  # don't label spending as income
        if pattern.search(text):
            return cat

    return "Income" if direction == "in" else "Uncategorized"
