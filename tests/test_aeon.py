"""
Acceptance tests for the AEON e-Statement parser, driven by the real
TESTDATA1 statement (as a text extract so the suite needs no binary PDF).

Run with:   pytest -q tests/test_aeon.py
"""

from datetime import date
from pathlib import Path

import pytest

from bank_extractor import aeon
from bank_extractor.aeon_parser import parse_file


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "TESTDATA1.txt"


@pytest.fixture(scope="module")
def parsed():
    txns, summaries = aeon.parse_and_classify(FIXTURE)
    return txns, summaries


def _acc(txns, name):
    return [t for t in txns if t.account == name]


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #
def test_total_transaction_count(parsed):
    txns, _ = parsed
    assert len(txns) == 118


def test_per_account_counts(parsed):
    txns, _ = parsed
    assert len(_acc(txns, "Savings Account-i")) == 109
    assert len(_acc(txns, "Duit Emergency")) == 4
    assert len(_acc(txns, "Park")) == 4
    assert len(_acc(txns, "Room Park")) == 1


# --------------------------------------------------------------------------- #
# Per-account totals (bugs 1 & 5)
# --------------------------------------------------------------------------- #
def _totals(txns, name):
    rows = _acc(txns, name)
    return (round(sum(t.money_out for t in rows), 2),
            round(sum(t.money_in for t in rows), 2))

def test_savings_totals(parsed):
    txns, _ = parsed
    out, inn = _totals(txns, "Savings Account-i")
    assert out == 7341.29
    assert inn == 6981.66

def test_duit_emergency_totals(parsed):
    txns, summaries = parsed
    out, inn = _totals(txns, "Duit Emergency")
    assert out == 4008.72
    assert inn == 2001.81

def test_park_totals(parsed):
    txns, _ = parsed
    out, inn = _totals(txns, "Park")
    assert out == 511.00
    assert inn == 1.16

def test_room_park_totals(parsed):
    txns, _ = parsed
    out, inn = _totals(txns, "Room Park")
    assert out == 0.00
    assert inn == 0.64


# --------------------------------------------------------------------------- #
# Closing balances / reconciliation against the bank's printed summary
# --------------------------------------------------------------------------- #
def test_reconciliation_all_pass(parsed):
    txns, summaries = parsed
    recons = {r.account: r for r in aeon.report.reconcile_accounts(txns, summaries)}
    assert recons["Savings Account-i"].opening == 474.57
    assert recons["Savings Account-i"].closing_computed == 114.94
    assert recons["Duit Emergency"].closing_computed == 1.81
    assert recons["Park"].closing_computed == 196.25
    assert recons["Room Park"].closing_computed == 250.76
    for r in recons.values():
        assert r.status == "PASS", f"{r.account} failed reconciliation"


# --------------------------------------------------------------------------- #
# Direction & balance correctness (bug 1)
# --------------------------------------------------------------------------- #
def test_direction_not_always_in(parsed):
    txns, _ = parsed
    assert any(t.money_out > 0 for t in txns)
    assert any(t.money_in > 0 for t in txns)
    # money_in must never hold the balance: no money_in equal to its own balance
    for t in txns:
        if t.money_in > 0 and t.balance is not None:
            assert t.money_in != t.balance or t.money_out == 0

def test_every_row_passes_balance_check(parsed):
    txns, _ = parsed
    bad = [t for t in txns if t.balance_check == "FAIL"]
    assert not bad, f"{len(bad)} rows failed the running-balance check"


# --------------------------------------------------------------------------- #
# Two-line Visa Purchase rows (bug 3)
# --------------------------------------------------------------------------- #
def test_visa_purchase_rows(parsed):
    txns, _ = parsed
    visa = [t for t in txns if t.method == "Visa"]
    assert len(visa) == 12
    assert round(sum(t.money_out for t in visa), 2) == 81.46
    # all Visa rows must carry a transaction date from the 2nd line
    assert all(t.transaction_date is not None for t in visa)

def test_visa_transaction_date_kept(parsed):
    txns, _ = parsed
    first_visa = next(t for t in txns if t.method == "Visa")
    assert first_visa.posting_date == date(2026, 8, 2)
    assert first_visa.transaction_date == date(2026, 7, 31)
    assert first_visa.money_out == 4.00


# --------------------------------------------------------------------------- #
# Opening/Closing rows excluded (bug 4)
# --------------------------------------------------------------------------- #
def test_no_balance_metadata_rows(parsed):
    txns, _ = parsed
    for t in txns:
        assert "opening balance" not in t.description.lower()
        assert "closing balance" not in t.description.lower()


# --------------------------------------------------------------------------- #
# Amount / RM stripped from description, counterparty correct (bug 2)
# --------------------------------------------------------------------------- #
def test_description_has_no_amount(parsed):
    txns, _ = parsed
    for t in txns:
        assert "RM" not in t.description.split("-")[-1][-6:] or "RM" not in t.description
    # explicit: no "RM <num>" left anywhere
    import re
    for t in txns:
        assert not re.search(r"RM\s*[\d,]+\.\d{2}", t.description)

def test_counterparty_extracted(parsed):
    txns, _ = parsed
    shell = next(t for t in txns if t.posting_date == date(2026, 8, 1)
                 and "SHELL - REKO" in t.description)
    assert shell.counterparty == "SHELL - REKO SEKSYE"
    assert shell.method == "MyDebit"
    assert shell.money_out == 14.99


# --------------------------------------------------------------------------- #
# Classification (bugs 6) + cashflow figures
# --------------------------------------------------------------------------- #
def test_purchases_not_income(parsed):
    txns, _ = parsed
    for t in txns:
        if t.tx_type == "Spending":
            assert t.category != "Income"
    # a cafe / warung / laundry must not be "Internal / Own account"
    laundry = next(t for t in txns if "SIMPLE LAUNDRY" in t.description)
    assert laundry.category == "Laundry"
    cafe = next(t for t in txns if "Makdah Cafe" in t.description)
    assert cafe.category == "Food & Dining"

def test_cashflow_figures(parsed):
    txns, _ = parsed
    cash = aeon.report.cashflow_summary(txns)
    assert cash["real_spending"] == 985.29
    assert cash["own_account_out"] == 4356.00
    assert cash["own_account_in"] == 2423.90

def test_internal_and_own_excluded_from_spending(parsed):
    txns, _ = parsed
    for t in txns:
        if t.tx_type in ("Internal", "Own account"):
            # these must not be counted as spending/income categories
            assert t.category == "Internal / Own account"


# --------------------------------------------------------------------------- #
# Account column present (bug 5)
# --------------------------------------------------------------------------- #
def test_account_column(parsed):
    txns, _ = parsed
    accounts = {t.account for t in txns}
    assert accounts == {"Savings Account-i", "Duit Emergency", "Park", "Room Park"}
