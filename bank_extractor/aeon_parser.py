"""
aeon_parser.py
==============

A precise parser for AEON Bank (Malaysia) e-Statements.

Why a dedicated parser?
-----------------------
AEON e-statements have a specific, well-defined layout that the generic
column-sniffing parser gets wrong. This module encodes the real structure:

  * Multiple accounts in one PDF, each introduced by an "Account summary" block
    (Savings Account-i, plus "pockets" like Duit Emergency / Park / Room Park).
  * Each transaction row starts with a posting date "dd Mon yy".
  * "Visa Purchase" rows span TWO lines: the amount/balance live on the second
    line, which also carries a "Transaction date: dd Mon yy".
  * "Opening balance" / "Closing balance" rows are metadata, not transactions.
  * Amounts are "-RM x" (money out) or "RM x" (money in); every row also prints
    the running balance, which we use to verify the sign.

The parser returns a list of ``AeonTransaction`` plus the per-account summary
blocks (so we can reconcile against the bank's own printed totals).

Reading the PDF
---------------
We get the page text with pdfplumber using ``layout=True`` (falls back to plain
extraction). We can also parse a pre-extracted text file, which is what the
tests do so they don't need the binary PDF or native libraries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
@dataclass
class AeonTransaction:
    posting_date: date
    account: str
    description: str                 # full cleaned narrative (no amount/RM)
    counterparty: str                # best-effort "who"
    method: str                      # MyDebit / Visa / DuitNowQR / ...
    money_in: float                  # >= 0
    money_out: float                 # >= 0
    balance: Optional[float]         # running balance printed on the row
    transaction_date: Optional[date] = None   # the "Transaction date:" if present
    source_page: int = 0
    tx_type: str = ""                # Spending | Income | Profit | Internal | Own account | P2P in | P2P out
    category: str = ""
    balance_check: str = ""          # "ok" | "FAIL" | "n/a"

    @property
    def signed_amount(self) -> float:
        return self.money_in - self.money_out


@dataclass
class AccountSummary:
    """The bank's own printed 'Account summary' block for one account."""
    name: str
    account_no: str = ""
    total_withdrawal: Optional[float] = None   # printed as -RM x (stored positive)
    total_deposits: Optional[float] = None
    closing_balance: Optional[float] = None
    opening_balance: Optional[float] = None    # taken from the "Opening balance" row
    first_page: int = 0


# --------------------------------------------------------------------------- #
# Low-level value parsing
# --------------------------------------------------------------------------- #
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

_DATE_RE = re.compile(r"^(\d{2})\s+([A-Za-z]{3})\s+(\d{2})")
_TXN_DATE_RE = re.compile(r"transaction date:\s*(\d{2})\s+([A-Za-z]{3})\s+(\d{2})", re.I)

# an amount token like "-RM 2,008.72" or "RM 21.00"
_AMOUNT_RE = re.compile(r"(-?)\s*RM\s*([\d,]+\.\d{2})")


def _parse_dmy(dd: str, mon: str, yy: str) -> Optional[date]:
    m = _MONTHS.get(mon.title())
    if not m:
        return None
    try:
        return date(2000 + int(yy), m, int(dd))
    except ValueError:
        return None


def parse_statement_date(token: str) -> Optional[date]:
    m = _DATE_RE.match(token.strip())
    if not m:
        return None
    return _parse_dmy(*m.groups())


def _money(num: str) -> float:
    return float(num.replace(",", ""))


# --------------------------------------------------------------------------- #
# Method + counterparty extraction
# --------------------------------------------------------------------------- #
# Known "method" phrases, longest first so e.g. "MyDebit Purchase" wins.
_METHODS = [
    "MyDebit Purchase", "Visa Purchase", "DuitQR P2P Transfer",
    "Intrabank transfer", "Fund transfer", "Fund Transfer",
    "Transfer to Account", "Transfer to Pot", "Profit Earned",
    "DuitNowQR", "DuitNow", "QR Payment",
]

# tails on the description that are noise once we've captured the method
_TAIL_NOISE = re.compile(
    r"\s*-\s*(QR\s*Payment|QR\d+|QR Payment|d)\s*$", re.I)


def split_description(raw_desc: str) -> tuple[str, str, str]:
    """
    Turn a raw AEON narrative into (clean_description, counterparty, method).

    Examples:
      "SHELL - REKO SEKSYE - MyDebit Purchase"
          -> ("SHELL - REKO SEKSYE - MyDebit Purchase", "SHELL - REKO SEKSYE", "MyDebit")
      "MUHAMMAD HAZIQ DANIEL BIN ROSLI - DuitNow - Fund transfer"
          -> (..., "MUHAMMAD HAZIQ DANIEL BIN ROSLI", "Fund transfer")
      "Park - Transfer to Account"
          -> (..., "Park", "Transfer to Account")
      "AHMAD RAFIQ BIN ROSLI - DuitNowQR - QR71373798 - DuitQR P2P Transfer"
          -> (..., "AHMAD RAFIQ BIN ROSLI", "DuitQR P2P Transfer")
    """
    desc = re.sub(r"\s+", " ", raw_desc).strip()

    # Method: find the longest known method phrase present.
    method = ""
    for cand in _METHODS:
        if re.search(r"\b" + re.escape(cand) + r"\b", desc, re.I):
            # normalize a couple of names
            method = {
                "MyDebit Purchase": "MyDebit",
                "Visa Purchase": "Visa",
                "Fund Transfer": "Fund transfer",
            }.get(cand, cand)
            break

    # Counterparty: everything before the first " - <method/channel>" marker.
    # Split on " - " and drop channel/method/ref fragments.
    parts = [p.strip() for p in desc.split(" - ")]
    channel_words = {
        "mydebit purchase", "visa purchase", "duitnowqr", "duitnow",
        "intrabank transfer", "fund transfer", "transfer to account",
        "transfer to pot", "qr payment", "profit earned",
        "duitqr p2p transfer",
    }
    cp_parts: list[str] = []
    for p in parts:
        pl = p.lower()
        if pl in channel_words:
            break
        if re.fullmatch(r"qr\d+", pl):      # QR reference like QR71373798
            break
        if pl == "d":                        # truncated "Fund transfer - d"
            break
        cp_parts.append(p)
    counterparty = " - ".join(cp_parts).strip() or desc

    return desc, counterparty, method


# --------------------------------------------------------------------------- #
# Page-level parsing
# --------------------------------------------------------------------------- #
# Lines that are headers/footers/notices we skip entirely.
_SKIP_SUBSTRINGS = (
    "aeon bank", "uoa corporate", "avenue 10", "jalan kerinchi", "phone :",
    "email :", "website :", "estatement", "e-statement", "important notice",
    "protected by pidm", "the items and balances", "if you have any inquiries",
    "muhammad haziq daniel bin rosli\n", "membership no", "statement period",
    "lot 3", "kolej pendeta", "bandar baru bangi", "malaysia.", "tap or scan",
    "to view e-invoice", "date description", "transactions",
    "total withdrawal", "total deposits", "closing balance", "page ",
    "august 2026", "1 - 31",
)


def _is_noise(line: str) -> bool:
    low = line.strip().lower()
    if not low:
        return True
    for s in _SKIP_SUBSTRINGS:
        if s in low:
            return True
    return False


def _extract_account_summary(page_text: str, page_no: int) -> Optional[AccountSummary]:
    """Parse the 'Account summary' block that appears at the top of a new account."""
    if "account summary" not in page_text.lower():
        return None
    lines = [l.rstrip() for l in page_text.splitlines()]
    name = ""
    account_no = ""
    tw = td = cb = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "account summary":
            # the account name is the next non-empty line
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j].strip()
                if nxt:
                    name = nxt
                    # an account number may follow
                    if j + 1 < len(lines) and re.fullmatch(r"\d{6,}", lines[j + 1].strip()):
                        account_no = lines[j + 1].strip()
                    break
        if "total withdrawal" in line.lower():
            m = _AMOUNT_RE.search(line)
            if m:
                tw = _money(m.group(2))
        if "total deposits" in line.lower():
            m = _AMOUNT_RE.search(line)
            if m:
                td = _money(m.group(2))
        if "closing balance" in line.lower() and "opening" not in line.lower():
            m = _AMOUNT_RE.search(line)
            if m:
                cb = _money(m.group(2))
    if not name:
        return None
    return AccountSummary(name=name, account_no=account_no,
                          total_withdrawal=tw, total_deposits=td,
                          closing_balance=cb, first_page=page_no)


def _group_transaction_lines(page_text: str) -> list[list[str]]:
    """
    Group the raw lines of a page into transaction blocks.

    A block starts at a line beginning with a posting date ("dd Mon yy") and
    continues until the next such line. This correctly joins the two-line
    Visa Purchase rows.
    """
    blocks: list[list[str]] = []
    current: Optional[list[str]] = None
    for raw in page_text.splitlines():
        line = raw.rstrip()
        if _DATE_RE.match(line.strip()):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            # continuation line (e.g. "Transaction date: 31 Jul 26 -RM 4.00 RM 390.08")
            if line.strip() and not _is_noise(line):
                current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_block(block: list[str], account: str, page_no: int) -> Optional[AeonTransaction]:
    """Turn one grouped block of lines into a transaction (or None for metadata)."""
    joined = " ".join(l.strip() for l in block)
    joined = re.sub(r"\s+", " ", joined).strip()

    # posting date
    posting = parse_statement_date(joined)
    if posting is None:
        return None

    low = joined.lower()
    # metadata rows -> not transactions
    if "opening balance" in low or "closing balance" in low:
        return None

    # transaction date (if present on a continuation line)
    txn_date = None
    mtd = _TXN_DATE_RE.search(joined)
    if mtd:
        txn_date = _parse_dmy(*mtd.groups())

    # collect all RM amounts in order; last is balance, the one before is the amount
    amounts = list(_AMOUNT_RE.finditer(joined))
    if len(amounts) < 2:
        return None  # need at least amount + balance

    amount_m = amounts[-2]
    balance_m = amounts[-1]
    signed_sign = amount_m.group(1)      # "" or "-"
    amount_val = _money(amount_m.group(2))
    balance_val = _money(balance_m.group(2))

    money_out = amount_val if signed_sign == "-" else 0.0
    money_in = amount_val if signed_sign != "-" else 0.0

    # Build the clean description: the narrative between the posting date and
    # the amount section, with the "Transaction date: ..." phrase removed and
    # all "RM <num>" tokens (amount + balance) stripped off the end.
    desc = _DATE_RE.sub("", joined, count=1).strip()
    desc = _TXN_DATE_RE.sub("", desc).strip()
    desc = re.sub(r"\s*-?\s*RM\s*[\d,]+\.\d{2}.*$", "", desc).strip()
    desc = desc.strip(" -")

    _, counterparty, method = split_description(desc)

    return AeonTransaction(
        posting_date=posting,
        account=account,
        description=desc,
        counterparty=counterparty,
        method=method,
        money_in=round(money_in, 2),
        money_out=round(money_out, 2),
        balance=round(balance_val, 2),
        transaction_date=txn_date,
        source_page=page_no,
    )


def _opening_balance(page_text: str) -> Optional[float]:
    for line in page_text.splitlines():
        if "opening balance" in line.lower():
            m = _AMOUNT_RE.search(line)
            if m:
                return _money(m.group(2))
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def parse_pages(pages: list[str]) -> tuple[list[AeonTransaction], dict[str, AccountSummary]]:
    """
    Parse a list of page texts (one string per PDF page) into transactions and
    per-account summaries.

    The 'current account' is whatever the most recent 'Account summary' block
    named; pages without a summary block (the continuation pages of the main
    account) inherit the current account.
    """
    transactions: list[AeonTransaction] = []
    summaries: dict[str, AccountSummary] = {}
    current_account = ""

    for idx, page_text in enumerate(pages, start=1):
        summ = _extract_account_summary(page_text, idx)
        if summ:
            current_account = summ.name
            if summ.name not in summaries:
                summaries[summ.name] = summ
            # capture opening balance for this account if present on the page
            ob = _opening_balance(page_text)
            if ob is not None and summaries[summ.name].opening_balance is None:
                summaries[summ.name].opening_balance = ob

        # even on summary pages, also grab opening balance for the running account
        ob = _opening_balance(page_text)
        if ob is not None and current_account in summaries \
                and summaries[current_account].opening_balance is None:
            summaries[current_account].opening_balance = ob

        for block in _group_transaction_lines(page_text):
            tx = _parse_block(block, current_account, idx)
            if tx is not None:
                transactions.append(tx)

    return transactions, summaries


def read_pdf_pages(path: str | Path) -> list[str]:
    """Extract per-page text from a PDF using pdfplumber (layout-aware)."""
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Reading PDF statements needs 'pdfplumber'. Install: pip install pdfplumber"
        ) from e
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or page.extract_text() or ""
            pages.append(text)
    return pages


def read_text_pages(path: str | Path, delimiter: str = "\f") -> list[str]:
    """
    Read a pre-extracted text dump and split into pages.

    Pages are separated by a form-feed ('\\f', what `pdftotext` emits) or, if
    none is present, by lines like 'Page N of M'.
    """
    text = Path(path).read_text(encoding="utf-8")
    if delimiter in text:
        return text.split(delimiter)
    # fall back to splitting after each "Page N of M"
    pages, buf = [], []
    for line in text.splitlines():
        buf.append(line)
        if re.search(r"page\s+\d+\s+of\s+\d+", line, re.I):
            pages.append("\n".join(buf))
            buf = []
    if buf:
        pages.append("\n".join(buf))
    return pages


def parse_file(path: str | Path) -> tuple[list[AeonTransaction], dict[str, AccountSummary]]:
    """Parse an AEON statement from a PDF or a pre-extracted .txt dump."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        pages = read_pdf_pages(path)
    else:
        pages = read_text_pages(path)
    return parse_pages(pages)
