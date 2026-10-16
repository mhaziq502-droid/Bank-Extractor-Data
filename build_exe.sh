#!/usr/bin/env bash
# ============================================================
#  Build a standalone executable for Bank Statement Extractor
#  on Linux or macOS. (For a Windows .exe, run build_exe.bat
#  on a Windows machine.)
# ============================================================
set -e

echo
echo "=== Bank Statement Extractor - build ==="
echo

# 1. Virtual environment
if [ ! -d venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 2. Dependencies
echo "Installing dependencies..."
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-build.txt

# 3. Build
echo
echo "Building executable..."
pyinstaller --noconfirm BankExtractor.spec

echo
echo "============================================================"
echo " Done! Your app is here:"
echo "    dist/BankExtractor"
echo "============================================================"
