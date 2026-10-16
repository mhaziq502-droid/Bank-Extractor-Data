"""
gui.py
======

The desktop window. Lets you:
  * add one or many bank statement files (CSV / Excel / PDF)
  * extract + clean the data with one click
  * see a quick dashboard (totals, date range, top categories)
  * export everything to a formatted Excel workbook (and CSV)

Built with Tkinter so it runs anywhere Python runs and packages cleanly into
a standalone .exe with PyInstaller.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import (
    Tk, StringVar, END, filedialog, messagebox,
    Listbox, Frame, Label, Button, Scrollbar,
    SINGLE, EXTENDED, BOTH, LEFT, RIGHT, X, Y, TOP, BOTTOM,
)
from tkinter import ttk

from . import __version__
from .parser import parse_files, SUPPORTED_EXTENSIONS
from . import analyzer, exporter


BG = "#f4f6fb"
ACCENT = "#305496"
GREEN = "#27AE60"
RED = "#C0392B"


class BankExtractorApp:
    def __init__(self, root: Tk):
        self.root = root
        self.files: list[str] = []
        self.df = None  # clean transactions DataFrame

        root.title(f"Bank Statement Extractor v{__version__}")
        root.geometry("860x620")
        root.minsize(760, 560)
        root.configure(bg=BG)

        self._build_header()
        self._build_file_section()
        self._build_action_section()
        self._build_dashboard()
        self._build_status_bar()

    # ----------------------------------------------------------------- UI build
    def _build_header(self):
        header = Frame(self.root, bg=ACCENT, height=70)
        header.pack(fill=X)
        Label(
            header, text="  Bank Statement Extractor",
            bg=ACCENT, fg="white", font=("Segoe UI", 18, "bold"),
        ).pack(side=LEFT, pady=16)
        Label(
            header, text="Turn raw statements into clean, sorted data  ",
            bg=ACCENT, fg="#d6e0f5", font=("Segoe UI", 10),
        ).pack(side=RIGHT, pady=22)

    def _build_file_section(self):
        wrap = Frame(self.root, bg=BG)
        wrap.pack(fill=X, padx=16, pady=(14, 6))

        Label(wrap, text="1.  Add your bank statement files",
              bg=BG, fg="#333", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        Label(wrap, text="Supported: CSV, Excel (.xlsx/.xls), PDF. Add as many as you like.",
              bg=BG, fg="#777", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))

        box = Frame(wrap, bg=BG)
        box.pack(fill=X)

        list_frame = Frame(box, bg=BG)
        list_frame.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.file_list = Listbox(
            list_frame, selectmode=EXTENDED, height=6,
            yscrollcommand=scrollbar.set, font=("Segoe UI", 9),
            activestyle="none",
        )
        self.file_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.config(command=self.file_list.yview)

        btns = Frame(box, bg=BG)
        btns.pack(side=LEFT, fill=Y, padx=(10, 0))
        Button(btns, text="Add Files", width=14, command=self.add_files,
               bg=ACCENT, fg="white", relief="flat",
               font=("Segoe UI", 9, "bold"), cursor="hand2").pack(pady=2)
        Button(btns, text="Remove Selected", width=14, command=self.remove_selected,
               relief="flat", font=("Segoe UI", 9), cursor="hand2").pack(pady=2)
        Button(btns, text="Clear All", width=14, command=self.clear_files,
               relief="flat", font=("Segoe UI", 9), cursor="hand2").pack(pady=2)

    def _build_action_section(self):
        wrap = Frame(self.root, bg=BG)
        wrap.pack(fill=X, padx=16, pady=(6, 6))
        Label(wrap, text="2.  Extract & clean", bg=BG, fg="#333",
              font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(4, 4))
        row = Frame(wrap, bg=BG)
        row.pack(fill=X)
        self.extract_btn = Button(
            row, text="Extract Data", width=18, command=self.run_extract,
            bg=GREEN, fg="white", relief="flat",
            font=("Segoe UI", 10, "bold"), cursor="hand2",
        )
        self.extract_btn.pack(side=LEFT)
        self.export_btn = Button(
            row, text="Export to Excel", width=18, command=self.run_export,
            bg=ACCENT, fg="white", relief="flat",
            font=("Segoe UI", 10, "bold"), cursor="hand2", state="disabled",
        )
        self.export_btn.pack(side=LEFT, padx=8)
        self.progress = ttk.Progressbar(row, mode="indeterminate", length=180)
        self.progress.pack(side=LEFT, padx=8)

    def _build_dashboard(self):
        wrap = Frame(self.root, bg=BG)
        wrap.pack(fill=BOTH, expand=True, padx=16, pady=(6, 6))
        Label(wrap, text="3.  Your money at a glance", bg=BG, fg="#333",
              font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(4, 6))

        cards = Frame(wrap, bg=BG)
        cards.pack(fill=X)
        self.card_vars = {
            "in": StringVar(value="-"),
            "out": StringVar(value="-"),
            "net": StringVar(value="-"),
            "tx": StringVar(value="-"),
        }
        self._card(cards, "Money In", self.card_vars["in"], GREEN)
        self._card(cards, "Money Out", self.card_vars["out"], RED)
        self._card(cards, "Net", self.card_vars["net"], ACCENT)
        self._card(cards, "Transactions", self.card_vars["tx"], "#555")

        # top categories table
        tbl_frame = Frame(wrap, bg=BG)
        tbl_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        Label(tbl_frame, text="Top spending categories", bg=BG, fg="#555",
              font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.cat_tree = ttk.Treeview(
            tbl_frame, columns=("cat", "spent", "pct"), show="headings", height=6
        )
        self.cat_tree.heading("cat", text="Category")
        self.cat_tree.heading("spent", text="Total Spent")
        self.cat_tree.heading("pct", text="% of Spend")
        self.cat_tree.column("cat", width=240)
        self.cat_tree.column("spent", width=140, anchor="e")
        self.cat_tree.column("pct", width=100, anchor="e")
        self.cat_tree.pack(fill=BOTH, expand=True, pady=4)

    def _card(self, parent, title, var, color):
        card = Frame(parent, bg="white", bd=1, relief="solid")
        card.pack(side=LEFT, expand=True, fill=X, padx=4)
        Label(card, text=title, bg="white", fg="#888",
              font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(8, 0))
        Label(card, textvariable=var, bg="white", fg=color,
              font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=10, pady=(0, 8))

    def _build_status_bar(self):
        self.status = StringVar(value="Ready. Add some statement files to begin.")
        bar = Label(self.root, textvariable=self.status, bg="#e8ecf5", fg="#333",
                    anchor="w", font=("Segoe UI", 9), padx=10)
        bar.pack(fill=X, side=BOTTOM, ipady=4)

    # ----------------------------------------------------------------- actions
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select bank statement files",
            filetypes=[
                ("Bank statements", "*.csv *.xlsx *.xls *.pdf *.txt"),
                ("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"),
                ("PDF", "*.pdf"), ("All files", "*.*"),
            ],
        )
        added = 0
        for p in paths:
            if Path(p).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if p not in self.files:
                self.files.append(p)
                self.file_list.insert(END, os.path.basename(p))
                added += 1
        if added:
            self.status.set(f"Added {added} file(s). {len(self.files)} total ready to extract.")

    def remove_selected(self):
        for idx in reversed(self.file_list.curselection()):
            self.file_list.delete(idx)
            del self.files[idx]
        self.status.set(f"{len(self.files)} file(s) ready.")

    def clear_files(self):
        self.file_list.delete(0, END)
        self.files.clear()
        self.status.set("Cleared file list.")

    def run_extract(self):
        if not self.files:
            messagebox.showwarning("No files", "Please add at least one statement file first.")
            return
        self.extract_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.progress.start(12)
        self.status.set("Extracting and cleaning data...")
        threading.Thread(target=self._extract_worker, daemon=True).start()

    def _extract_worker(self):
        try:
            transactions = parse_files(self.files)
            df = analyzer.transactions_to_dataframe(transactions)
            errors = getattr(parse_files, "last_errors", [])
            self.root.after(0, self._extract_done, df, errors)
        except Exception as e:
            self.root.after(0, self._extract_failed, str(e))

    def _extract_done(self, df, errors):
        self.progress.stop()
        self.extract_btn.config(state="normal")
        self.df = df
        if df is None or df.empty:
            self.status.set("No transactions found. Check the file format.")
            messagebox.showinfo(
                "Nothing extracted",
                "Couldn't find any transactions in those files.\n\n"
                "Tip: make sure the files contain columns like Date, Description, "
                "and Debit/Credit or Amount.",
            )
            return
        self._refresh_dashboard(df)
        self.export_btn.config(state="normal")
        msg = f"Done. {len(df)} transactions extracted and sorted by date."
        if errors:
            msg += f" ({len(errors)} file(s) had issues)"
            messagebox.showwarning("Some files had issues", "\n".join(errors))
        self.status.set(msg)

    def _extract_failed(self, err):
        self.progress.stop()
        self.extract_btn.config(state="normal")
        self.status.set("Extraction failed.")
        messagebox.showerror("Extraction failed", err)

    def _refresh_dashboard(self, df):
        ov = analyzer.build_overview(df)
        self.card_vars["in"].set(f"{ov['money_in']:,.2f}")
        self.card_vars["out"].set(f"{ov['money_out']:,.2f}")
        self.card_vars["net"].set(f"{ov['net']:,.2f}")
        self.card_vars["tx"].set(str(ov["transactions"]))

        for item in self.cat_tree.get_children():
            self.cat_tree.delete(item)
        cats = analyzer.category_breakdown(df)
        for _, r in cats.head(8).iterrows():
            self.cat_tree.insert(
                "", END,
                values=(r["Category"], f"{r['Total Spent']:,.2f}", f"{r['% of Spend']}%"),
            )

    def run_export(self):
        if self.df is None or self.df.empty:
            return
        default = f"clean_bank_data_{datetime.now():%Y%m%d_%H%M}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Save clean data as",
            defaultextension=".xlsx",
            initialfile=default,
            filetypes=[("Excel workbook", "*.xlsx"), ("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                exporter.export_to_csv(self.df, path)
            else:
                exporter.export_to_excel(self.df, path)
            self.status.set(f"Saved: {path}")
            if messagebox.askyesno("Export complete",
                                   f"Saved to:\n{path}\n\nOpen the folder now?"):
                self._open_folder(path)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    @staticmethod
    def _open_folder(path):
        folder = os.path.dirname(os.path.abspath(path))
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception:
            pass


def main():
    root = Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    BankExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
