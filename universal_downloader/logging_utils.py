"""Logging configuration, secret redaction, and error message classification."""

from __future__ import annotations

import logging
import re
import sys
from typing import Optional

from universal_downloader.models import AppConfig, Platform

LOGGER = logging.getLogger("universal_downloader")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class SecretFilter(logging.Filter):
    """Prevent obvious credential-like values from entering logs."""

    SECRET_PATTERNS = (
        re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(api[_-]?secret\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(access[_-]?token\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(authorization\s*:\s*)\S+"),
        re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in self.SECRET_PATTERNS:
            message = pattern.sub(r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(config: AppConfig) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if config.debug else (
        logging.INFO if config.verbose else logging.WARNING
    )

    LOGGER.setLevel(level)
    LOGGER.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        config.log_dir / "downloader.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretFilter())

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretFilter())

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(console_handler)


def clean_error_message(message: str) -> str:
    """Remove terminal color codes and normalize yt-dlp error text."""
    cleaned = ANSI_ESCAPE_RE.sub("", message).strip()

    if cleaned.upper().startswith("ERROR:"):
        cleaned = cleaned[6:].strip()

    return cleaned


def format_download_error(
    exc: Exception,
    platform: Optional[Platform] = None,
) -> str:
    message = clean_error_message(str(exc))
    lowered = message.lower()

    if (
        platform == Platform.TIKTOK
        and "unable to extract universal data" in lowered
    ):
        return (
            f"{message}\n\n"
            "TikTok may be temporarily rate-limiting automated requests. Suggestions:\n"
            "  • Wait a few moments and retry\n"
            "  • Pass browser cookies: --cookies-from-browser edge (or chrome/firefox)\n"
            "  • Or export cookies to a Netscape file and pass: --cookies cookies.txt"
        )

    if "dpapi" in lowered or "could not decrypt" in lowered or "app-bound" in lowered:
        return (
            f"{message}\n\n"
            "Note: Newer Chromium browsers (Chrome v127+) protect cookies with App-Bound Encryption.\n"
            "If browser cookie extraction fails:\n"
            "  • Export cookies with an extension (e.g. 'Get cookies.txt LOCALLY')\n"
            "  • Supply the exported file via: --cookies cookies.txt\n"
            "  • Or use Firefox cookies: --cookies-from-browser firefox"
        )

    if "sign in to confirm you're not a bot" in lowered or "bot detection" in lowered or "the page needs to be reloaded" in lowered or "ssap" in lowered:
        return (
            f"{message}\n\n"
            "YouTube verification/SSAP reload triggered. Suggestions:\n"
            "  • The engine automatically rotates client player profiles (Android, iOS, mWeb)\n"
            "  • If issues persist, supply browser cookies: --cookies-from-browser chrome (or edge/firefox)\n"
            "  • Supply an exported Netscape cookie file: --cookies cookies.txt\n"
            "  • Use a proxy: --proxy http://username:password@proxyserver:port"
        )

    return message


def is_tiktok_rehydration_error(message: str) -> bool:
    lowered = clean_error_message(message).lower()
    return "unable to extract universal data" in lowered


TIKTOK_INTERNAL_RETRIES = 8
TIKTOK_RETRY_DELAYS = (1, 2, 3, 5, 8, 10, 12, 15)


def is_non_retryable_error(message: str) -> bool:
    """
    Check if an error is permanently unrecoverable.
    Note: Transient issues like HTTP 429 and rate limits are intentionally
    EXCLUDED so they can be retried with exponential backoff.
    """
    message = clean_error_message(message).lower()

    permanent_markers = (
        "unable to extract webpage video data",
        "unable to extract webpage",
        "unsupported url",
        "private",
        "login required",
        "sign in",
        "authentication",
        "captcha",
        "http error 401",
        "http error 403",
        "http error 404",
        "video unavailable",
        "your ip address is blocked",
        "video not available",
    )

    return any(marker in message for marker in permanent_markers)
