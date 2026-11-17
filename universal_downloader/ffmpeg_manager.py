"""FFmpeg discovery, auto-download, and runtime dependency management.

Ensures FFmpeg and FFprobe are transparently available without requiring
manual user installation or interrupting the user workflow.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

LOGGER = logging.getLogger("universal_downloader")

# Prebuilt static builds from official yt-dlp release repositories
FFMPEG_DOWNLOAD_URLS = {
    "windows_x64": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "linux_x64": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    "linux_arm64": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    "macos_universal": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-osx64-gpl.zip",
}


def get_local_bin_dir() -> Path:
    """Return the application binary cache directory across platforms."""
    system = sys.platform
    if system == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        bin_dir = Path(base) / "UniversalDownloader" / "bin"
    elif system == "darwin":
        bin_dir = Path.home() / "Library" / "Application Support" / "UniversalDownloader" / "bin"
    else:
        # Linux and other Unixes
        data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        bin_dir = Path(data_home) / "UniversalDownloader" / "bin"

    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        # Fallback to workspace bin directory if user directory has restricted access
        fallback = Path.cwd() / ".universal_downloader" / "bin"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except (PermissionError, OSError):
            pass

    return bin_dir


def _candidate_ffmpeg_paths() -> list[Path]:
    """Return ordered list of locations where FFmpeg might reside."""
    system = sys.platform
    exe_name = "ffmpeg.exe" if system == "win32" else "ffmpeg"
    candidates: list[Path] = []

    # 1. Explicit environment variable override
    env_ffmpeg = os.environ.get("FFMPEG_PATH") or os.environ.get("FFMPEG_BINARY")
    if env_ffmpeg:
        candidates.append(Path(env_ffmpeg))

    # 2. Local app data bin cache
    candidates.append(get_local_bin_dir() / exe_name)

    # 3. Next to current running Python executable / PyInstaller standalone
    exe_dir = Path(sys.executable).parent
    candidates.append(exe_dir / exe_name)
    candidates.append(exe_dir / "bin" / exe_name)
    candidates.append(exe_dir / "ffmpeg" / exe_name)

    # 4. Next to downloader.py or project root
    cwd = Path.cwd()
    candidates.append(cwd / exe_name)
    candidates.append(cwd / "bin" / exe_name)

    # 5. Standard Windows installation paths
    if system == "win32":
        user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", user_profile / "AppData" / "Local"))
        candidates.extend([
            Path(r"C:\ffmpeg\bin") / exe_name,
            Path(r"C:\Program Files\ffmpeg\bin") / exe_name,
            Path(r"C:\Program Files (x86)\ffmpeg\bin") / exe_name,
            Path(r"C:\ProgramData\chocolatey\bin") / exe_name,
            user_profile / "scoop" / "shims" / exe_name,
            user_profile / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / exe_name,
            local_app_data / "Microsoft" / "WinGet" / "Links" / exe_name,
        ])
    elif system == "darwin":
        candidates.extend([
            Path("/opt/homebrew/bin") / exe_name,
            Path("/usr/local/bin") / exe_name,
            Path("/usr/bin") / exe_name,
        ])
    else:
        candidates.extend([
            Path("/usr/bin") / exe_name,
            Path("/usr/local/bin") / exe_name,
            Path("/opt/ffmpeg/bin") / exe_name,
        ])

    return candidates


def find_ffmpeg() -> Optional[Path]:
    """Search for an existing ffmpeg binary and ensure its folder is in PATH."""
    system = sys.platform
    exe_name = "ffmpeg.exe" if system == "win32" else "ffmpeg"

    # 1. System PATH
    found = shutil.which("ffmpeg") or (shutil.which(exe_name) if system == "win32" else None)
    if found:
        found_path = Path(found).resolve()
        _ensure_in_path(found_path.parent)
        return found_path

    # 2. Known directories
    for candidate in _candidate_ffmpeg_paths():
        try:
            if candidate.is_file():
                resolved = candidate.resolve()
                _ensure_in_path(resolved.parent)
                return resolved
        except (PermissionError, OSError):
            continue

    return None


def find_ffprobe() -> Optional[Path]:
    """Search for an existing ffprobe binary."""
    system = sys.platform
    exe_name = "ffprobe.exe" if system == "win32" else "ffprobe"

    found = shutil.which("ffprobe") or (shutil.which(exe_name) if system == "win32" else None)
    if found:
        return Path(found).resolve()

    for candidate in _candidate_ffmpeg_paths():
        probe_candidate = candidate.with_name(exe_name)
        try:
            if probe_candidate.is_file():
                return probe_candidate.resolve()
        except (PermissionError, OSError):
            continue

    return None


def _ensure_in_path(directory: Path) -> None:
    """Prepend directory to process PATH if not already present."""
    dir_str = str(directory)
    current_path = os.environ.get("PATH", "")
    paths = current_path.split(os.pathsep)
    if dir_str not in paths:
        os.environ["PATH"] = f"{dir_str}{os.pathsep}{current_path}"


def get_download_url() -> Optional[str]:
    """Determine the appropriate static build URL for current OS and architecture."""
    system = sys.platform
    machine = platform.machine().lower()

    if system == "win32":
        return FFMPEG_DOWNLOAD_URLS["windows_x64"]
    if system == "darwin":
        return FFMPEG_DOWNLOAD_URLS["macos_universal"]
    if system.startswith("linux"):
        if "arm" in machine or "aarch64" in machine:
            return FFMPEG_DOWNLOAD_URLS["linux_arm64"]
        return FFMPEG_DOWNLOAD_URLS["linux_x64"]

    return None


def download_and_install_ffmpeg(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Download and unpack static FFmpeg binaries into the local user cache directory."""
    url = get_download_url()
    if not url:
        LOGGER.warning("No prebuilt FFmpeg distribution URL available for platform '%s'.", sys.platform)
        return None

    bin_dir = get_local_bin_dir()
    system = sys.platform
    exe_name = "ffmpeg.exe" if system == "win32" else "ffmpeg"
    probe_name = "ffprobe.exe" if system == "win32" else "ffprobe"
    final_ffmpeg = bin_dir / exe_name

    msg = f"Auto-downloading standalone FFmpeg engine to {bin_dir}..."
    LOGGER.info(msg)
    if progress_callback:
        progress_callback(msg)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "UniversalDownloader/1.0 (Turnkey Media Client)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total_size = resp.headers.get("Content-Length")
            total_bytes = int(total_size) if total_size else 0

            downloaded = 0
            temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=".download")
            try:
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    temp_archive.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes and downloaded % (1024 * 1024 * 5) < 1024 * 64:
                        pct = (downloaded / total_bytes) * 100
                        p_msg = f"Downloading FFmpeg: {pct:.1f}% ({downloaded // (1024*1024)} MB)"
                        LOGGER.info(p_msg)
                        if progress_callback:
                            progress_callback(p_msg)

                temp_archive.close()

                # Extract only ffmpeg and ffprobe from the archive
                if url.endswith(".zip"):
                    with zipfile.ZipFile(temp_archive.name, "r") as zf:
                        for member in zf.namelist():
                            base_member = os.path.basename(member).lower()
                            if base_member in (exe_name.lower(), probe_name.lower()):
                                target_path = bin_dir / os.path.basename(member)
                                with zf.open(member) as src, open(target_path, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                if system != "win32":
                                    target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                elif url.endswith((".tar.xz", ".tar.gz", ".tar.bz2")):
                    with tarfile.open(temp_archive.name, "r:*") as tf:
                        for member in tf.getmembers():
                            base_member = os.path.basename(member.name).lower()
                            if base_member in (exe_name.lower(), probe_name.lower()):
                                extracted_file = tf.extractfile(member)
                                if extracted_file:
                                    target_path = bin_dir / os.path.basename(member.name)
                                    with open(target_path, "wb") as dst:
                                        shutil.copyfileobj(extracted_file, dst)
                                    if system != "win32":
                                        target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            finally:
                try:
                    os.unlink(temp_archive.name)
                except OSError:
                    pass

        if final_ffmpeg.is_file():
            _ensure_in_path(bin_dir)
            success_msg = f"Standalone FFmpeg ready at {final_ffmpeg}."
            LOGGER.info(success_msg)
            if progress_callback:
                progress_callback(success_msg)
            return final_ffmpeg

    except Exception as exc:
        LOGGER.warning("Could not auto-download FFmpeg: %s. Continuing in direct stream mode.", exc)

    return None


def ensure_ffmpeg(
    auto_download: bool = True,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Ensure FFmpeg is available; automatically install static build if missing."""
    existing = find_ffmpeg()
    if existing:
        return existing

    if auto_download:
        return download_and_install_ffmpeg(progress_callback=progress_callback)

    return None


def is_ffmpeg_available() -> bool:
    """Check if FFmpeg is currently accessible."""
    return find_ffmpeg() is not None
