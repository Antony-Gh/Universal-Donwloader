# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for Universal Media Downloader.
Compiles downloader.py and the universal_downloader package into a
standalone, single-file Windows executable (downloader.exe).
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

# Collect curl_cffi for yt-dlp browser TLS impersonation (Instagram, TikTok, etc.)
extra_binaries = []
extra_datas = []
extra_hidden = []
try:
    _c_datas, _c_bins, _c_hidden = collect_all("curl_cffi")
    extra_datas.extend(_c_datas)
    extra_binaries.extend(_c_bins)
    extra_hidden.extend(_c_hidden)
except Exception:
    pass

# Collect all submodules from yt_dlp and universal_downloader
hidden_imports = [
    "universal_downloader",
    "universal_downloader.cli",
    "universal_downloader.engine",
    "universal_downloader.extractor",
    "universal_downloader.batch",
    "universal_downloader.history",
    "universal_downloader.watcher",
    "universal_downloader.notify",
    "universal_downloader.protocol",
    "universal_downloader.updater",
    "universal_downloader.config",
    "universal_downloader.formats",
    "universal_downloader.models",
    "universal_downloader.profile",
    "universal_downloader.progress",
    "universal_downloader.console",
    "universal_downloader.logging_utils",
    "universal_downloader.exceptions",
    "universal_downloader.utils.fs",
    "universal_downloader.utils.net",
    "sqlite3",
    "ctypes",
    "urllib",
    "mutagen",
    "certifi",
] + collect_submodules("yt_dlp") + extra_hidden

datas = [
    ("universal_downloader", "universal_downloader"),
] + collect_data_files("certifi") + extra_datas

a = Analysis(
    ["downloader.py"],
    pathex=["."],
    binaries=extra_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PySide6", "PyQt5", "PyQt6"],
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
    name="downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Console mode is required for IPC stdout / stderr JSON streaming
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
