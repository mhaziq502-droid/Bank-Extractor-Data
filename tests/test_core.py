"""
Core unit tests. Run with:  pytest -q

These cover the pure logic (date/amount/party parsing, categorization) plus
an end-to-end parse of the sample CSV files into a clean DataFrame.
"""

from datetime import date
from pathlib import Path

import pytest

from bank_extractor.parser import parse_date, parse_amount, extract_party, parse_files
from bank_extractor.categorizer import categorize
from bank_extractor import analyzer


SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# ----------------------------------------------------------------- date parsing
@pytest.mark.parametrize("value,expected", [
    ("15/03/2024", date(2024, 3, 15)),
    ("2024-03-15", date(2024, 3, 15)),
    ("15 Mar 2024", date(2024, 3, 15)),
    ("15-Mar-2024", date(2024, 3, 15)),
    ("notadate", None),
    ("", None),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


# --------------------------------------------------------------- amount parsing
@pytest.mark.parametrize("value,expected", [
    ("1,234.56", 1234.56),
    ("(500.00)", -500.00),
    ("RM 1,000.00", 1000.00),
    ("250.75 DR", -250.75),
    ("300.00 CR", 300.00),
    ("1.234,56", 1234.56),
    ("-45.20", -45.20),
    ("", None),
])
def test_parse_amount(value, expected):
    result = parse_amount(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# ------------------------------------------------------------------- party
def test_extract_party():
    assert "Ahmad" in extract_party("DUITNOW TRANSFER TO AHMAD BIN ALI")


# --------------------------------------------------------------- categorizer
@pytest.mark.parametrize("desc,direc,expected", [
    ("GRABFOOD ORDER", "out", "Food & Dining"),
    ("PETRONAS STATION", "out", "Transport"),
    ("TNB ELECTRICITY BILL", "out", "Bills & Utilities"),
    ("SALARY CREDIT", "in", "Income"),
    ("SHOPEE PAYMENT", "out", "Shopping"),
])
def test_categorize(desc, direc, expected):
    assert categorize(desc, "", direc) == expected


# ----------------------------------------------------------- end-to-end parsing
def test_parse_sample_files():
    files = [SAMPLES / "sample_statement_1.csv", SAMPLES / "sample_statement_2.csv"]
    txns = parse_files(files)
    assert len(txns) == 20  # 10 + 10 rows, all valid

    df = analyzer.transactions_to_dataframe(txns)
    assert not df.empty
    assert list(df["Date"]) == sorted(df["Date"])  # sorted by date

    overview = analyzer.build_overview(df)
    assert overview["transactions"] == 20
    assert overview["money_in"] > 0
    assert overview["money_out"] > 0


def test_summaries_build():
    files = [SAMPLES / "sample_statement_1.csv", SAMPLES / "sample_statement_2.csv"]
    df = analyzer.transactions_to_dataframe(parse_files(files))
    assert not analyzer.daily_summary(df).empty
    assert not analyzer.monthly_summary(df).empty
    assert not analyzer.category_breakdown(df).empty
    assert not analyzer.budget_forecast(df).empty
