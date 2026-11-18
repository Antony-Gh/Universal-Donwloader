"""System and user storage path resolution with safe fallbacks."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def is_directory_writable(path: Path) -> bool:
    """Check if a directory can be created and written to."""
    try:
        target = path.resolve()
        while not target.exists() and target != target.parent:
            target = target.parent
        if not target.exists():
            return False

        test_file = target / f".write_test_{os.getpid()}"
        try:
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
            return True
        except (PermissionError, OSError):
            return False
    except Exception:
        return False


def is_system_or_program_dir(path: Path) -> bool:
    """Check if a path is located inside a system, Windows Program Files, or system binary root."""
    try:
        resolved = str(path.resolve()).lower()
        system_roots: list[str] = []

        if sys.platform == "win32":
            for env_var in (
                "PROGRAMFILES",
                "PROGRAMFILES(X86)",
                "PROGRAMW6432",
                "SYSTEMROOT",
                "WINDIR",
            ):
                val = os.environ.get(env_var)
                if val:
                    system_roots.append(str(Path(val).resolve()).lower())
        else:
            system_roots.extend(["/usr", "/opt", "/etc", "/var", "/bin", "/sbin"])

        return any(resolved.startswith(root) for root in system_roots)
    except Exception:
        return False


def get_default_log_dir() -> Path:
    """Return a standard user-writable directory for application logs."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "UniversalDownloader" / "logs"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "UniversalDownloader"
    else:
        state_home = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        return Path(state_home) / "universal_downloader" / "logs"


def get_default_data_dir() -> Path:
    """Return a standard user-writable directory for application databases and caches."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "UniversalDownloader"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "UniversalDownloader"
    else:
        data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return Path(data_home) / "universal_downloader"


def get_default_download_dir() -> Path:
    """Return the user's primary Downloads folder, falling back to home or temp."""
    downloads = Path.home() / "Downloads"
    if is_directory_writable(downloads):
        return downloads
    if is_directory_writable(Path.home()):
        return Path.home()
    temp_downloads = Path(tempfile.gettempdir()) / "UniversalDownloader" / "downloads"
    return temp_downloads
