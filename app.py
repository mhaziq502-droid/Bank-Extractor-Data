"""
app.py
======

Main entry point for the Bank Statement Extractor desktop app.
This is the file PyInstaller turns into the standalone .exe.

Run it directly with:  python app.py
"""

from bank_extractor.gui import main

if __name__ == "__main__":
    main()
