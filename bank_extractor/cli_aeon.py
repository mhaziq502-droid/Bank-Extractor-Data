"""
cli_aeon.py
===========

Command-line runner for AEON Bank e-Statements.

    python -m bank_extractor.cli_aeon TESTDATA1.pdf -o clean.xlsx

Accepts a PDF or a pre-extracted .txt dump (pdftotext -layout output).
Prints the per-account reconciliation and the real-vs-internal cashflow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import aeon


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="aeon-extractor",
        description="Extract an AEON Bank e-Statement into a reconciled Excel report.",
    )
    p.add_argument("input", help="AEON statement (.pdf or extracted .txt)")
    p.add_argument("-o", "--output", default="aeon_clean.xlsx",
                   help="Output .xlsx (default: aeon_clean.xlsx)")
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: file not found: {src}", file=sys.stderr)
        return 2

    result = aeon.process(src, out_xlsx=args.output)

    print(f"Parsed {len(result.transactions)} transactions "
          f"across {len(result.summaries)} account(s).\n")
    print(f"{'Account':<22}{'Opening':>12}{'In':>12}{'Out':>12}{'Closing':>12}  Recon")
    for r in result.recons:
        print(f"{r.account:<22}{r.opening:>12,.2f}{r.total_in:>12,.2f}"
              f"{r.total_out:>12,.2f}{r.closing_computed:>12,.2f}  {r.status}")

    c = result.cashflow
    print("\nCashflow (real money vs. internal shuffling)")
    print(f"  Real spending            : {c['real_spending']:>12,.2f}")
    print(f"  Real income              : {c['real_income']:>12,.2f}")
    print(f"  Own-account out / in     : {c['own_account_out']:>12,.2f} / {c['own_account_in']:,.2f}")
    print(f"  Internal (pocket) out/in : {c['internal_out']:>12,.2f} / {c['internal_in']:,.2f}")

    print(f"\nSaved report to: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
