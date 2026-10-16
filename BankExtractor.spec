# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building the standalone Bank Statement Extractor executable.

Build with:   pyinstaller BankExtractor.spec
Output:       dist/BankExtractor.exe  (Windows)  |  dist/BankExtractor (Linux/macOS)
"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pandas',
        'openpyxl',
        'xlsxwriter',
        'pdfplumber',
        'bank_extractor',
        'bank_extractor.parser',
        'bank_extractor.analyzer',
        'bank_extractor.categorizer',
        'bank_extractor.exporter',
        'bank_extractor.gui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'notebook', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BankExtractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # add 'assets/icon.ico' here if you want a custom icon
)
