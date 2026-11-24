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


def _init_ssl_certs() -> None:
    import os
    try:
        import certifi
        ca_file = certifi.where()
        if ca_file and os.path.exists(ca_file):
            os.environ.setdefault("SSL_CERT_FILE", ca_file)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)
            os.environ.setdefault("CURL_CA_BUNDLE", ca_file)
            import ssl
            ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=ca_file)
    except Exception:
        pass


_init_ssl_certs()
APP_CONFIG: dict[str, Any] = _load_shared_app_config()

__version__: str = str(APP_CONFIG.get("version_name") or "4.4.0")
__version_code__: int = int(APP_CONFIG.get("version_code") or 440)
__app_name__: str = str(APP_CONFIG.get("app_name") or "Universal Media Downloader")
__github_owner__: str = str(APP_CONFIG.get("github_owner") or "Antony-Gh")
__github_repo__: str = str(APP_CONFIG.get("github_repo") or "Universal-Donwloader")
