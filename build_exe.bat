@echo off
REM ============================================================
REM  Build the standalone Windows .exe for Bank Statement Extractor
REM  Just double-click this file on a Windows machine with Python
REM  installed, or run it from a command prompt.
REM ============================================================

echo.
echo === Bank Statement Extractor - Windows build ===
echo.

REM 1. Create a virtual environment (keeps your system clean)
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

REM 2. Install runtime + build dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-build.txt

REM 3. Build the single-file executable
echo.
echo Building BankExtractor.exe ...
pyinstaller --noconfirm BankExtractor.spec

echo.
echo ============================================================
echo  Done!  Your app is here:
echo     dist\BankExtractor.exe
echo  Double-click it to run. No Python needed to run it.
echo ============================================================
echo.
pause
