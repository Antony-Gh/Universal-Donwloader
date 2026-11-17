"""
Universal Media Downloader
Production-grade downloader for publicly accessible media.
Reads shared app metadata (version_name, version_code, app_name, GitHub repo) directly from app_config.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load_shared_app_config() -> dict[str, Any]:
    candidates = [
        Path(__file__).resolve().parent.parent / "app_config.json",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass) / "app_config.json")

    for path in candidates:
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


APP_CONFIG: dict[str, Any] = _load_shared_app_config()

__version__: str = str(APP_CONFIG.get("version_name") or "2.5.0")
__version_code__: int = int(APP_CONFIG.get("version_code") or 250)
__app_name__: str = str(APP_CONFIG.get("app_name") or "Universal Media Downloader")
__github_owner__: str = str(APP_CONFIG.get("github_owner") or "Antony-Gh")
__github_repo__: str = str(APP_CONFIG.get("github_repo") or "Universal-Donwloader")
