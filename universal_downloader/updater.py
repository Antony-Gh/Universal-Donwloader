"""Self-updater module for yt-dlp and extractor components."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import urllib.request
from typing import Optional

LOGGER = logging.getLogger("universal_downloader")


def get_installed_ytdlp_version() -> str:
    try:
        import yt_dlp
        return getattr(yt_dlp, "__version__", None) or getattr(getattr(yt_dlp, "version", None), "__version__", "unknown")
    except ImportError:
        return "not installed"


def get_latest_pypi_version(package_name: str = "yt-dlp", timeout: int = 10) -> Optional[str]:
    url = f"https://pypi.org/pypi/{package_name}/json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "UniversalDownloader/1.1 (Updater)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("info", {}).get("version")
    except Exception as exc:
        LOGGER.warning("Could not check PyPI for %s updates: %s", package_name, exc)
        return None


def update_ytdlp() -> tuple[bool, str]:
    """Upgrade yt-dlp via pip in the current Python environment."""
    current_ver = get_installed_ytdlp_version()
    latest_ver = get_latest_pypi_version("yt-dlp")

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        new_ver = get_installed_ytdlp_version()
        msg = (
            f"yt-dlp updated successfully.\n"
            f"Previous version: {current_ver}\n"
            f"Current version:  {new_ver}"
        )
        return True, msg
    except subprocess.CalledProcessError as exc:
        err = exc.stderr or exc.stdout or str(exc)
        return False, f"Failed to update yt-dlp: {err}"
    except Exception as exc:
        return False, f"Unexpected error during update: {exc}"
