"""
parser.py
=========

Reads raw bank statement files (CSV, Excel, PDF) and turns them into a clean,
normalized list of transactions.

Each transaction is normalized to this shape:

    {
        "date":        datetime.date,   # when the transaction happened
        "description": str,             # raw description / narrative text
        "party":       str,             # best-effort "who" (payee/payer)
        "direction":   "in" | "out",    # money in or money out
        "amount":      float,           # always positive
        "balance":     float | None,    # running balance if the file had one
        "source_file": str,             # which uploaded file this came from
    }

Different banks lay their statements out differently, so this module tries hard
to auto-detect which columns mean what (date / description / debit / credit /
amount / balance) rather than assuming a fixed format.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


# --------------------------------------------------------------------------- #
# Transaction model
# --------------------------------------------------------------------------- #
@dataclass
class Transaction:
    date: date
    description: str
    amount: float
    direction: str  # "in" or "out"
    party: str = ""
    balance: Optional[float] = None
    source_file: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat() if self.date else ""
        return d


# --------------------------------------------------------------------------- #
# Column name detection
# --------------------------------------------------------------------------- #
# Lower-cased keyword lists used to guess what a column means.
DATE_KEYS = ["date", "tarikh", "transaction date", "posting date", "value date", "trans date"]
DESC_KEYS = ["description", "narrative", "details", "transaction", "particulars",
             "remarks", "butiran", "keterangan", "reference", "memo", "payee"]
DEBIT_KEYS = ["debit", "withdrawal", "paid out", "money out", "dr", "keluar", "debet", "spend"]
CREDIT_KEYS = ["credit", "deposit", "paid in", "money in", "cr", "masuk", "kredit"]
AMOUNT_KEYS = ["amount", "jumlah", "value", "transaction amount", "amt"]
BALANCE_KEYS = ["balance", "baki", "running balance", "closing balance", "bal"]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _find_column(columns: list[str], keys: list[str]) -> Optional[str]:
    """Return the first column whose normalized name matches any key."""
    norm_cols = {col: _norm(col) for col in columns}
    # exact match first
    for col, n in norm_cols.items():
        if n in keys:
            return col
    # then "contains"
    for col, n in norm_cols.items():
        for k in keys:
            if k in n:
                return col
    return None


# --------------------------------------------------------------------------- #
# Value parsing helpers
# --------------------------------------------------------------------------- #
_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%m/%d/%Y", "%m-%d-%Y",
    "%d/%m/%y", "%d-%m-%y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %y",
]


def parse_date(value) -> Optional[date]:
    """Best-effort parse of a date from many common formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # last resort: let pandas try
    try:
        ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(ts):
            return ts.date()
    except Exception:
        pass
    return None


def parse_amount(value) -> Optional[float]:
    """Parse a monetary value. Handles currency symbols, commas, parentheses, trailing CR/DR."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "-"):
        return None

    negative = False
    # (123.45) means negative
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    # trailing DR = debit (negative), CR = credit
    tail = s[-2:].upper()
    if tail == "DR":
        negative = True
        s = s[:-2]
    elif tail == "CR":
        s = s[:-2]

    # strip currency symbols / letters, keep digits . , -
    s = re.sub(r"[^0-9.,-]", "", s)
    if not s:
        return None

    # Handle both "1,234.56" and "1.234,56" styles
    if s.count(",") and s.count("."):
        if s.rfind(",") > s.rfind("."):
            # comma is decimal sep: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") and not s.count("."):
        # comma could be decimal (123,45) or thousands (1,234)
        if re.match(r"^-?\d{1,3}(,\d{3})+$", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")

    try:
        val = float(s)
    except ValueError:
        return None
    if s.startswith("-"):
        negative = True
        val = abs(val)
    return -val if negative else val


# --------------------------------------------------------------------------- #
# Party ("who to who") extraction
# --------------------------------------------------------------------------- #
_PARTY_PATTERNS = [
    r"(?:to|kepada|transfer to|trf to|payment to|duitnow to)\s*[:\-]?\s*(.+)",
    r"(?:from|daripada|received from|trf from|credit from)\s*[:\-]?\s*(.+)",
    r"(?:fpx|duitnow|ibg|instant transfer)\s*[:\-]?\s*(.+)",
]
_NOISE = re.compile(r"\b(ref|reference|txn|transaction|id|no)\s*[:#]?\s*\w+\b", re.I)


def extract_party(description: str) -> str:
    """Pull a human-ish 'who' out of a transaction description."""
    if not description:
        return ""
    desc = description.strip()
    for pat in _PARTY_PATTERNS:
        m = re.search(pat, desc, re.I)
        if m:
            cand = m.group(1).strip()
            cand = _NOISE.sub("", cand).strip(" -:*")
            if cand:
                return _norm_party(cand)
    # fall back to the longest "word-ish" chunk
    cleaned = _NOISE.sub("", desc).strip(" -:*")
    return _norm_party(cleaned)


def _norm_party(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    # trim trailing numeric refs
    s = re.sub(r"[\s\-]+\d{4,}$", "", s)
    return s[:60].title() if s.isupper() or s.islower() else s[:60]


# --------------------------------------------------------------------------- #
# Build Transaction objects from a normalized DataFrame
# --------------------------------------------------------------------------- #
def _rows_to_transactions(df: pd.DataFrame, source_file: str) -> list[Transaction]:
    cols = list(df.columns)
    date_col = _find_column(cols, DATE_KEYS)
    desc_col = _find_column(cols, DESC_KEYS)
    debit_col = _find_column(cols, DEBIT_KEYS)
    credit_col = _find_column(cols, CREDIT_KEYS)
    amount_col = _find_column(cols, AMOUNT_KEYS)
    balance_col = _find_column(cols, BALANCE_KEYS)

    # Avoid picking the same column twice
    if amount_col and amount_col in (debit_col, credit_col):
        amount_col = None

    transactions: list[Transaction] = []
    for _, row in df.iterrows():
        d = parse_date(row[date_col]) if date_col else None
        if d is None:
            continue  # rows without a date are headers/footers/noise

        description = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else ""

        amount = None
        direction = None

        if debit_col or credit_col:
            debit = parse_amount(row[debit_col]) if debit_col else None
            credit = parse_amount(row[credit_col]) if credit_col else None
            if credit:
                amount, direction = abs(credit), "in"
            elif debit:
                amount, direction = abs(debit), "out"
        if amount is None and amount_col:
            raw = parse_amount(row[amount_col])
            if raw is not None and raw != 0:
                direction = "in" if raw > 0 else "out"
                amount = abs(raw)

        if amount is None or amount == 0:
            continue

        balance = parse_amount(row[balance_col]) if balance_col else None

        transactions.append(
            Transaction(
                date=d,
                description=description,
                amount=round(amount, 2),
                direction=direction,
                party=extract_party(description),
                balance=round(balance, 2) if balance is not None else None,
                source_file=source_file,
            )
        )
    return transactions


# --------------------------------------------------------------------------- #
# Per-format readers
# --------------------------------------------------------------------------- #
def _find_header_row(raw: pd.DataFrame) -> int:
    """Scan the first ~20 rows to find the one that looks like a header."""
    best_row, best_score = 0, -1
    for i in range(min(20, len(raw))):
        values = [_norm(v) for v in raw.iloc[i].tolist() if pd.notna(v)]
        score = 0
        for keyset in (DATE_KEYS, DESC_KEYS, DEBIT_KEYS, CREDIT_KEYS, AMOUNT_KEYS, BALANCE_KEYS):
            if any(any(k in v for k in keyset) for v in values):
                score += 1
        if score > best_score:
            best_score, best_row = score, i
    return best_row


def read_csv(path: Path) -> list[Transaction]:
    raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False,
                      engine="python", on_bad_lines="skip")
    header_row = _find_header_row(raw)
    df = pd.read_csv(path, header=header_row, dtype=str, keep_default_na=False,
                     engine="python", on_bad_lines="skip")
    df.columns = [str(c) for c in df.columns]
    return _rows_to_transactions(df, path.name)


def read_excel(path: Path) -> list[Transaction]:
    all_tx: list[Transaction] = []
    xls = pd.ExcelFile(path)
    for sheet in xls.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
        if raw.empty:
            continue
        header_row = _find_header_row(raw)
        df = pd.read_excel(path, sheet_name=sheet, header=header_row, dtype=str)
        df.columns = [str(c) for c in df.columns]
        all_tx.extend(_rows_to_transactions(df, path.name))
    return all_tx


# PDF statements rarely have a clean table, so we parse line-by-line with regex.
_PDF_LINE = re.compile(
    r"""^(?P<date>\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}\s+\w{3}\s+\d{2,4})
        \s+(?P<desc>.+?)
        \s+(?P<amount>[-(]?[\d,]+\.\d{2}\)?(?:\s*(?:CR|DR))?)
        (?:\s+(?P<balance>[-(]?[\d,]+\.\d{2}\)?))?\s*$""",
    re.X | re.I,
)


def read_pdf(path: Path) -> list[Transaction]:
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Reading PDF statements needs the 'pdfplumber' package. "
            "Install it with: pip install pdfplumber"
        ) from e

    transactions: list[Transaction] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # First try structured tables (works for many bank PDFs)
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                header = [str(c or "") for c in table[0]]
                df = pd.DataFrame(table[1:], columns=header)
                df.columns = [str(c) for c in df.columns]
                transactions.extend(_rows_to_transactions(df, path.name))

            # Then fall back to line-by-line text parsing
            text = page.extract_text() or ""
            for line in text.splitlines():
                m = _PDF_LINE.match(line.strip())
                if not m:
                    continue
                d = parse_date(m.group("date"))
                if not d:
                    continue
                amt = parse_amount(m.group("amount"))
                if amt is None or amt == 0:
                    continue
                desc = m.group("desc").strip()
                transactions.append(
                    Transaction(
                        date=d,
                        description=desc,
                        amount=abs(amt),
                        direction="in" if amt > 0 else "out",
                        party=extract_party(desc),
                        balance=parse_amount(m.group("balance")) if m.group("balance") else None,
                        source_file=path.name,
                    )
                )

    # de-dupe table vs text double-reads within the same PDF
    return _dedupe(transactions)


def _dedupe(transactions: list[Transaction]) -> list[Transaction]:
    """Remove exact-duplicate transactions (same date, amount, direction, description)."""
    seen = set()
    out = []
    for t in transactions:
        key = (t.date, t.amount, t.direction, _norm(t.description))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".txt"}


def parse_file(path: str | Path) -> list[Transaction]:
    """Parse a single file into a list of Transactions."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".csv", ".txt"):
        return read_csv(path)
    if ext in (".xlsx", ".xls"):
        return read_excel(path)
    if ext == ".pdf":
        return read_pdf(path)
    raise ValueError(f"Unsupported file type: {ext}")


def parse_files(paths: Iterable[str | Path]) -> list[Transaction]:
    """Parse many files, merge them, de-duplicate, and sort by date."""
    all_tx: list[Transaction] = []
    errors: list[str] = []
    for p in paths:
        try:
            all_tx.extend(parse_file(p))
        except Exception as e:  # keep going even if one file fails
            errors.append(f"{Path(p).name}: {e}")
    all_tx = _dedupe(all_tx)
    all_tx.sort(key=lambda t: (t.date, t.description))
    if errors:
        # attach errors so the caller/GUI can surface them
        parse_files.last_errors = errors  # type: ignore[attr-defined]
    else:
        parse_files.last_errors = []  # type: ignore[attr-defined]
    return all_tx


parse_files.last_errors = []  # type: ignore[attr-defined]
