# 🏦 Bank Statement Extractor

Turn messy, raw bank statement files into **clean, sorted data** so you can see
exactly where your money goes — and forecast next month's budget.

Upload one file or many. The app reads every transaction, sorts them by date,
figures out **who you paid / who paid you**, totals your **spend per day and per
month**, groups spending into **categories**, and projects your **next month's
budget**. Then it exports everything into a tidy Excel workbook with charts.

---

## ✨ What it does

| Feature | Description |
|---|---|
| 📂 **Multi-file upload** | Add many statements at once (CSV, Excel, PDF). They're merged automatically. |
| 📅 **Sorts by date** | Every transaction is read and sorted into date order, across all files. |
| 🔁 **De-duplication** | Overlapping statements won't double-count the same transaction. |
| 👤 **Who-to-who** | Extracts the payee/payer ("party") from each transaction description. |
| 💸 **Daily spend summary** | Total money in / out and net, per day. |
| 📆 **Monthly summary** | Totals per calendar month. |
| 🏷️ **Auto-categorization** | Food, Transport, Bills, Shopping, Transfers, Income, and more. |
| 🥧 **Category breakdown** | See where your money goes, with a pie chart. |
| 🏆 **Top payees** | Who you send the most money to. |
| 🔮 **Budget forecast** | Projected spend for next month, overall and per category. |
| 📊 **Excel export** | One workbook, multiple sheets, with charts. CSV export too. |
| 🖥️ **Standalone .exe** | Build a Windows executable — no Python needed to run it. |

---

## 🚀 Getting the app (Windows .exe)

### Option A — Download a pre-built .exe (easiest)
Every push to GitHub automatically builds a Windows `.exe` using GitHub Actions.

1. Go to the repo's **Actions** tab.
2. Open the latest **"Build Windows EXE"** run.
3. Download the **`BankExtractor-windows`** artifact (it contains `BankExtractor.exe`).
4. Unzip and double-click `BankExtractor.exe`. Done — no installation needed.

> Tip: push a version tag like `v1.0.0` and the workflow also attaches the `.exe`
> to a GitHub **Release** for easy sharing.

### Option B — Build the .exe yourself on Windows
On a Windows machine with [Python 3.11+](https://www.python.org/downloads/) installed:

```bat
build_exe.bat
```

That script creates a virtual environment, installs everything, and produces
`dist\BankExtractor.exe`.

### Option C — Build on Linux/macOS
```bash
./build_exe.sh      # produces dist/BankExtractor
```

---

## 🧑‍💻 Running from source (any OS)

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2a. launch the desktop app
python app.py

# 2b. or use the command line
python -m bank_extractor.cli samples/sample_statement_1.csv samples/sample_statement_2.csv -o clean.xlsx
```

---

## 🖱️ How to use the app

1. **Add Files** — pick your bank statement files (CSV / Excel / PDF).
2. **Extract Data** — the app reads, cleans, sorts, and categorizes everything.
3. Check the **dashboard** (money in/out, net, top categories).
4. **Export to Excel** — save a full report with daily/monthly summaries,
   category breakdown, top payees, and the budget forecast.

---

## 📁 What the Excel report contains

| Sheet | What's in it |
|---|---|
| **Overview** | Headline totals and date range. |
| **Clean Transactions** | Every transaction, sorted by date, with category + who. |
| **Daily Summary** | Spend per day + a trend chart. |
| **Monthly Summary** | Totals per month. |
| **Category Breakdown** | Where your money goes + a pie chart. |
| **Top Payees** | Who you pay the most. |
| **Budget Forecast** | Projected spend for next month. |
| **Category Forecast** | Projected spend per category. |

---

## 🏦 AEON Bank (Malaysia) e-Statement parser

AEON e-statements have a fixed layout that the generic parser can't read
correctly, so there's a dedicated, high-accuracy parser for them in
`bank_extractor/aeon_parser.py` (+ `classifier.py`, `report.py`,
`exporter_aeon.py`).

```bash
# PDF (needs pdfplumber) or a pdftotext -layout dump
python -m bank_extractor.cli_aeon TESTDATA1.pdf -o clean.xlsx
```

```python
from bank_extractor import aeon
result = aeon.process("TESTDATA1.pdf", out_xlsx="clean.xlsx")
print(result.cashflow)      # real spending, own-account/internal net, ...
print(result.recons)        # per-account PASS/FAIL reconciliation
```

**What it gets right (previously bugs):**

| Area | Behaviour |
|---|---|
| Direction / balance | `Money In`/`Money Out` and `Balance` are correct; sign is verified against the running balance (`prev + amount == balance`), and any mismatch is flagged, not guessed. |
| Description cleanup | Amount, sign and `RM` are stripped out; `Counterparty` and `Method` (MyDebit, Visa, DuitNowQR, Intrabank/Fund transfer, Transfer to Account/Pot, Profit Earned) are split out. |
| Two-line Visa rows | The `Visa Purchase` + `Transaction date: …` second line is joined, so the amount/balance on that line are captured. Both the posting date and the transaction date are kept. |
| Opening/Closing | Treated as metadata, never imported as transactions. |
| Multiple accounts | Each account is detected from its `Account summary` block and tagged with an `Account` column. |
| No double counting | Pocket transfers that mirror the main account are classified `Internal`/`Own account` and excluded from real spending/income (shown separately in a Cashflow block). |
| Categories | Keyword map in **`bank_extractor/categories.yaml`** (edit it freely). A purchase is never labelled Income. |
| Reconciliation | The Overview sheet checks `opening + in − out == closing` against the bank's own printed summary and shows **PASS/FAIL** per account. |

**Output workbook (xlsx):**
- **Overview** — per account: opening, total in, total out, closing, PASS/FAIL
  reconciliation; plus real spending, real income, net own-account and net
  internal movement.
- **Transactions** — Date, Transaction Date, Account, Description, Counterparty,
  Method, Money In, Money Out, Balance, Type, Category, Source page.
- **By Category** — totals, share %, count (spending only).

**Tested against the real `TESTDATA1.pdf`** (`tests/test_aeon.py`): 118
transactions, exact per-account totals, 12 Visa rows = RM 81.46, real spending
RM 985.29, own-name transfers out RM 4,356.00 / in RM 2,423.90, and every row
passing the running-balance check. The test uses a text extract of the
statement so it runs without the binary PDF.

---

## 🔧 Supported statement formats

- **CSV** / **TXT** — any column layout; the app auto-detects Date, Description,
  Debit/Credit or Amount, and Balance columns (English & Malay headers).
- **Excel** (`.xlsx`, `.xls`) — all sheets are scanned.
- **PDF** — tables are extracted, with a line-by-line text fallback.

Different banks format statements differently, so the parser is built to adapt.
If a particular statement isn't read well, tweak the keyword lists in
`bank_extractor/parser.py` (column detection) and
`bank_extractor/categorizer.py` (spending categories).

---

## 🧪 Tests

```bash
pip install pytest
pytest -q
```

---

## 🗂️ Project structure

```
Bank-Extractor-Data/
├── app.py                      # desktop app entry point (packaged into the .exe)
├── bank_extractor/
│   ├── parser.py               # reads CSV/Excel/PDF -> normalized transactions
│   ├── categorizer.py          # keyword-based spending categories
│   ├── analyzer.py             # daily/monthly summaries, forecast, top payees
│   ├── exporter.py             # writes the Excel workbook with charts
│   ├── gui.py                  # Tkinter desktop interface
│   └── cli.py                  # command-line interface
├── samples/                    # example statement files to try
├── tests/                      # unit + end-to-end tests
├── BankExtractor.spec          # PyInstaller build config
├── build_exe.bat / .sh         # one-click build scripts
├── .github/workflows/build.yml # auto-builds the Windows .exe on GitHub
└── requirements*.txt
```

---

## 📝 Notes

- All processing is **local** — your statement data never leaves your computer.
- The forecast is a simple, transparent average-based projection you can trust
  and verify, not a black box.
