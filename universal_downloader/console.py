"""Console formatting, color styling, and status banners."""

from __future__ import annotations

import sys

from universal_downloader import __app_name__, __version__
from universal_downloader.models import AppConfig


def supports_color(config: AppConfig) -> bool:
    if config.no_color:
        return False
    return sys.stdout.isatty()


def ctext(text: str, code: str, config: AppConfig) -> str:
    if not supports_color(config):
        return text
    return f"\033[{code}m{text}\033[0m"


def success(text: str, config: AppConfig) -> None:
    print(ctext(f"✓ {text}", "32", config))


def failure(text: str, config: AppConfig) -> None:
    print(ctext(f"✗ {text}", "31", config))


def info(text: str, config: AppConfig) -> None:
    print(ctext(f"• {text}", "36", config))


def warning(text: str, config: AppConfig) -> None:
    print(ctext(f"! {text}", "33", config))


def print_banner(config: AppConfig) -> None:
    if config.json_output:
        return
    print()
    print("╔══════════════════════════════════════╗")
    print("║     Universal Media Downloader       ║")
    print(f"║              v{__version__:<14}         ║")
    print("╚══════════════════════════════════════╝")
    print()
