"""Self-updater module for yt-dlp and extractor components."""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from universal_downloader.ffmpeg_manager import get_local_bin_dir, _ensure_in_path

LOGGER = logging.getLogger("universal_downloader")


def get_installed_ytdlp_version() -> str:
    """Return the currently installed or cached yt-dlp version."""
    # 1. Check local bin cache for standalone yt-dlp binary
    bin_dir = get_local_bin_dir()
    exe_name = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    cached_exe = bin_dir / exe_name
    if cached_exe.is_file():
        try:
            res = subprocess.run([str(cached_exe), "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

    # 2. Check Python package if available
    try:
        import yt_dlp
        return getattr(yt_dlp, "__version__", None) or getattr(getattr(yt_dlp, "version", None), "__version__", "unknown")
    except ImportError:
        pass

    # 3. Check system PATH
    system_ytdlp = shutil.which("yt-dlp")
    if system_ytdlp:
        try:
            res = subprocess.run([system_ytdlp, "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

    return "not installed"


def get_latest_pypi_version(package_name: str = "yt-dlp", timeout: int = 10) -> Optional[str]:
    url = f"https://pypi.org/pypi/{package_name}/json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "UniversalDownloader/4.3 (Updater)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("info", {}).get("version")
    except Exception as exc:
        LOGGER.warning("Could not check PyPI for %s updates: %s", package_name, exc)
        return None


def get_latest_github_release(repo: str = "yt-dlp/yt-dlp", timeout: int = 10) -> Optional[dict]:
    """Query GitHub Releases API for latest release metadata."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "UniversalDownloader/4.3 (Updater)",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        LOGGER.warning("Could not check GitHub Releases for %s: %s", repo, exc)
        return None


def update_engine_binaries(
    target_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[bool, str]:
    """Download the latest standalone yt-dlp binary from GitHub Releases into the bin directory.
    
    Works independently of Python or pip, ensuring portable and frozen bundles stay updated.
    """
    dest_dir = target_dir or get_local_bin_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    _ensure_in_path(dest_dir)

    system = sys.platform
    if system == "win32":
        asset_name = "yt-dlp.exe"
        dest_file = dest_dir / "yt-dlp.exe"
    elif system == "darwin":
        asset_name = "yt-dlp_macos"
        dest_file = dest_dir / "yt-dlp"
    else:
        asset_name = "yt-dlp_linux"
        dest_file = dest_dir / "yt-dlp"

    download_url = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{asset_name}"
    tmp_file = dest_dir / f"{dest_file.name}.tmp_{os.getpid()}"

    LOGGER.info("Downloading latest engine binary from %s to %s", download_url, dest_file)
    req = urllib.request.Request(
        download_url,
        headers={"User-Agent": "UniversalDownloader/4.3 (EngineUpdater)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_file, "wb") as out_fp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_fp.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0:
                    progress_callback(downloaded, total)

        if tmp_file.stat().st_size < 1024 * 100:
            if tmp_file.exists():
                tmp_file.unlink()
            return False, "Downloaded engine binary is suspiciously small or corrupted."

        if dest_file.exists():
            try:
                dest_file.unlink()
            except OSError:
                old_file = dest_file.with_suffix(".old")
                if old_file.exists():
                    try:
                        old_file.unlink()
                    except OSError:
                        pass
                dest_file.rename(old_file)

        tmp_file.rename(dest_file)

        # Set executable permissions on Unix/macOS
        if system != "win32":
            dest_file.chmod(dest_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        new_ver = get_installed_ytdlp_version()
        return True, f"yt-dlp extraction engine updated successfully to {new_ver}."
    except Exception as exc:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
        LOGGER.error("Failed to update engine binary: %s", exc)
        return False, f"Failed to download engine update: {exc}"


def ensure_aria2(target_dir: Optional[Path] = None) -> Optional[Path]:
    """Ensure aria2c multi-connection downloader is available on PATH or in local bin."""
    # 1. Existing on PATH
    found = shutil.which("aria2c")
    if found:
        return Path(found)

    # 2. Existing in local bin cache
    dest_dir = target_dir or get_local_bin_dir()
    exe_name = "aria2c.exe" if sys.platform == "win32" else "aria2c"
    cached = dest_dir / exe_name
    if cached.is_file():
        _ensure_in_path(dest_dir)
        return cached

    return None


def update_ytdlp() -> tuple[bool, str]:
    """Upgrade yt-dlp via pip when in normal python environment, or binary release when frozen."""
    current_ver = get_installed_ytdlp_version()
    
    # If running in a frozen executable (PyInstaller) or pip is unavailable, download binary
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        return update_engine_binaries()

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        new_ver = get_installed_ytdlp_version()
        msg = (
            f"yt-dlp updated successfully.\n"
            f"Previous version: {current_ver}\n"
            f"Current version:  {new_ver}"
        )
        return True, msg
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        LOGGER.warning("pip upgrade failed (%s), falling back to binary download", exc)
        return update_engine_binaries()
    except Exception as exc:
        return False, f"Unexpected error during update: {exc}"
