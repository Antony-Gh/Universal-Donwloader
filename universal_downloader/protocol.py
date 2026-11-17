"""Windows custom protocol registration for browser and desktop integration (downloader://)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

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
    """Register downloader:// protocol in Windows registry for the current user."""
    if not sys.platform.startswith("win"):
        return False, "Custom protocol registration is only supported on Windows."

    try:
        import winreg

        script_path = (executable_path or (Path(__file__).parent.parent / "downloader.py")).resolve()
        python_exe = sys.executable

        # Command to invoke when browser triggers downloader://<url>
        command_str = f'"{python_exe}" "{script_path}" "%1"'

        key_path = r"Software\Classes\downloader"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Universal Downloader Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command_str)

        return True, "Registered downloader:// protocol successfully in Windows Registry."
    except Exception as exc:
        LOGGER.exception("Failed to register custom protocol.")
        return False, f"Protocol registration failed: {exc}"


def unregister_protocol() -> tuple[bool, str]:
    """Unregister downloader:// protocol from Windows registry."""
    if not sys.platform.startswith("win"):
        return False, "Custom protocol registration is only supported on Windows."

    try:
        import winreg

        key_path = r"Software\Classes\downloader"

        # Recursive delete of subkeys
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
        LOGGER.exception("Failed to unregister custom protocol.")
        return False, f"Protocol unregistration failed: {exc}"
