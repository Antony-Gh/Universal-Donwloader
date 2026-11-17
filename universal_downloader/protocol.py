"""Custom protocol registration for browser and desktop integration (downloader://).

Supports Windows Registry and Linux FreeDesktop (XDG mime handler).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("universal_downloader")


def clean_protocol_url(raw: str) -> str:
    """Strip custom protocol scheme prefix if present."""
    val = raw.strip()
    if val.lower().startswith("downloader://"):
        return val[13:]
    if val.lower().startswith("downloader:"):
        return val[11:]
    return val


def register_protocol(executable_path: Optional[Path] = None) -> tuple[bool, str]:
    """Register downloader:// protocol in system desktop environment."""
    script_path = (executable_path or (Path(__file__).parent.parent / "downloader.py")).resolve()

    # 1. Windows Registry Registration
    if sys.platform.startswith("win"):
        try:
            import winreg

            python_exe = sys.executable
            command_str = f'"{python_exe}" "{script_path}" "%1"'

            key_path = r"Software\Classes\downloader"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Universal Downloader Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command_str)

            return True, "Registered downloader:// protocol successfully in Windows Registry."
        except Exception as exc:
            LOGGER.exception("Failed to register Windows custom protocol.")
            return False, f"Protocol registration failed: {exc}"

    # 2. Linux FreeDesktop XDG Application Handler
    elif sys.platform.startswith("linux"):
        try:
            apps_dir = Path.home() / ".local" / "share" / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            desktop_file = apps_dir / "universal-downloader-handler.desktop"

            python_bin = sys.executable
            exec_line = f'"{python_bin}" "{script_path}" %u'

            desktop_content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Universal Downloader URL Handler\n"
                f"Exec={exec_line}\n"
                "StartupNotify=false\n"
                "Terminal=false\n"
                "MimeType=x-scheme-handler/downloader;\n"
                "Categories=Network;\n"
            )
            desktop_file.write_text(desktop_content, encoding="utf-8")

            if shutil.which("xdg-mime"):
                subprocess.run(
                    ["xdg-mime", "default", "universal-downloader-handler.desktop", "x-scheme-handler/downloader"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            if shutil.which("update-desktop-database"):
                subprocess.run(
                    ["update-desktop-database", str(apps_dir)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            return True, f"Registered downloader:// protocol in Linux XDG desktop entry: {desktop_file}"
        except Exception as exc:
            LOGGER.exception("Failed to register Linux custom protocol.")
            return False, f"Protocol registration failed: {exc}"

    return False, f"Custom protocol registration is not currently supported on {sys.platform}."


def unregister_protocol() -> tuple[bool, str]:
    """Unregister downloader:// protocol from system desktop environment."""
    if sys.platform.startswith("win"):
        try:
            import winreg

            key_path = r"Software\Classes\downloader"

            def delete_key_tree(root, subkey):
                try:
                    with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as hkey:
                        while True:
                            try:
                                child = winreg.EnumKey(hkey, 0)
                                delete_key_tree(root, f"{subkey}\\{child}")
                            except OSError:
                                break
                    winreg.DeleteKey(root, subkey)
                except FileNotFoundError:
                    pass

            delete_key_tree(winreg.HKEY_CURRENT_USER, key_path)
            return True, "Unregistered downloader:// protocol from Windows Registry."
        except Exception as exc:
            LOGGER.exception("Failed to unregister Windows custom protocol.")
            return False, f"Protocol unregistration failed: {exc}"

    elif sys.platform.startswith("linux"):
        try:
            apps_dir = Path.home() / ".local" / "share" / "applications"
            desktop_file = apps_dir / "universal-downloader-handler.desktop"
            if desktop_file.exists():
                desktop_file.unlink()

            if shutil.which("update-desktop-database"):
                subprocess.run(
                    ["update-desktop-database", str(apps_dir)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            return True, "Unregistered downloader:// protocol from Linux XDG desktop entries."
        except Exception as exc:
            LOGGER.exception("Failed to unregister Linux custom protocol.")
            return False, f"Protocol unregistration failed: {exc}"

    return False, f"Custom protocol unregistration is not currently supported on {sys.platform}."
