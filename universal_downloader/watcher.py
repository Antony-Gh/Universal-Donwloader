"""System clipboard monitor daemon for automated link detection."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes
from typing import Callable, Optional

from universal_downloader.console import info, success, warning
from universal_downloader.engine import DownloadEngine
from universal_downloader.models import Platform
from universal_downloader.utils.net import detect_platform, normalize_url

LOGGER = logging.getLogger("universal_downloader")


def get_windows_clipboard_text() -> Optional[str]:
    """Retrieve text from Windows clipboard via Win32 API without external dependencies."""
    if not sys.platform.startswith("win"):
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    if not user32.OpenClipboard(None):
        return None

    try:
        CF_UNICODETEXT = 13
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def watch_clipboard(
    engine: DownloadEngine,
    interval: float = 1.0,
    auto_download: bool = True,
    callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Continuously poll system clipboard and download media URLs on copy."""
    config = engine.config
    last_seen: Optional[str] = None

    if not config.json_output and not config.json_stream:
        info("Clipboard watcher active. Copy any video or media URL to download (Ctrl+C to quit)...", config)

    try:
        while True:
            text = get_windows_clipboard_text()
            if text and text != last_seen:
                last_seen = text
                candidate = text.strip()

                if candidate.startswith(("http://", "https://", "www.")):
                    try:
                        norm = normalize_url(candidate)
                        platform = detect_platform(norm)
                        if platform != Platform.UNKNOWN:
                            if callback:
                                callback(norm)

                            if auto_download:
                                if not config.json_output and not config.json_stream:
                                    print()
                                    info(f"Detected media URL from clipboard: {norm}", config)
                                engine.download(norm)
                    except Exception as exc:
                        LOGGER.debug("Watcher ignored non-media clipboard text: %s", exc)

            time.sleep(max(0.2, interval))
    except KeyboardInterrupt:
        if not config.json_output and not config.json_stream:
            print("\nClipboard watcher stopped.")
