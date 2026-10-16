"""
aeon.py
=======

High-level pipeline for AEON Bank e-Statements. One call does everything:
parse -> classify -> reconcile -> export.

    from bank_extractor import aeon
    result = aeon.process("TESTDATA1.pdf", out_xlsx="clean.xlsx")
    print(result.transactions, result.summaries)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import aeon_parser, classifier, report
from .aeon_parser import AeonTransaction, AccountSummary


@dataclass
class AeonResult:
    transactions: list[AeonTransaction]
    summaries: dict[str, AccountSummary]
    recons: list
    cashflow: dict


def process(input_path: str | Path, out_xlsx: str | Path | None = None) -> AeonResult:
    """Parse + classify + reconcile an AEON statement, optionally writing xlsx."""
    transactions, summaries = aeon_parser.parse_file(input_path)
    classifier.classify_all(transactions, summaries)
    recons = report.reconcile_accounts(transactions, summaries)
    cash = report.cashflow_summary(transactions)
    if out_xlsx:
        from . import exporter_aeon  # lazy: only needs pandas when exporting
        exporter_aeon.export(transactions, summaries, out_xlsx)
    return AeonResult(transactions=transactions, summaries=summaries,
                      recons=recons, cashflow=cash)


def parse_and_classify(input_path: str | Path):
    """Parse + classify without exporting (handy for tests)."""
    transactions, summaries = aeon_parser.parse_file(input_path)
    classifier.classify_all(transactions, summaries)
    return transactions, summaries
