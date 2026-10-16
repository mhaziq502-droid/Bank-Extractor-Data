"""
cli.py
======

Command-line version of the extractor, for when you'd rather run it in a
terminal or script it. Example:

    python -m bank_extractor.cli statement1.csv statement2.pdf -o clean.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parser import parse_files
from . import analyzer, exporter


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bank-extractor",
        description="Extract and clean bank statement data into a tidy Excel/CSV report.",
    )
    parser.add_argument("files", nargs="+", help="Bank statement files (CSV, Excel, PDF).")
    parser.add_argument("-o", "--output", default="clean_bank_data.xlsx",
                        help="Output file (.xlsx or .csv). Default: clean_bank_data.xlsx")
    args = parser.parse_args(argv)

    paths = [Path(f) for f in args.files]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("ERROR: these files were not found:", ", ".join(missing), file=sys.stderr)
        return 2

    print(f"Reading {len(paths)} file(s)...")
    transactions = parse_files(paths)
    errors = getattr(parse_files, "last_errors", [])
    for e in errors:
        print(f"  ! {e}", file=sys.stderr)

    df = analyzer.transactions_to_dataframe(transactions)
    if df.empty:
        print("No transactions found. Check the file format.", file=sys.stderr)
        return 1

    ov = analyzer.build_overview(df)
    print(f"\nExtracted {ov['transactions']} transactions "
          f"({ov['first_date']} to {ov['last_date']})")
    print(f"  Money in : {ov['money_in']:,.2f}")
    print(f"  Money out: {ov['money_out']:,.2f}")
    print(f"  Net      : {ov['net']:,.2f}")

    out = Path(args.output)
    if out.suffix.lower() == ".csv":
        exporter.export_to_csv(df, out)
    else:
        exporter.export_to_excel(df, out)
    print(f"\nSaved clean report to: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
