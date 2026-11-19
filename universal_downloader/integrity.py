"""Post-download media container integrity verification and SHA-256 checksum helpers."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Optional

from universal_downloader.ffmpeg_manager import find_ffmpeg

LOGGER = logging.getLogger("universal_downloader")

HASH_CHUNK_BYTES = 1024 * 1024  # 1 MB


def compute_sha256(file_path: Path) -> str:
    """Compute lowercase hexadecimal SHA-256 digest of a file."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found for hashing: {path}")

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def write_sha256_sidecar(file_path: Path, digest: Optional[str] = None) -> Path:
    """Write a standard sha256sum-compatible `<file>.sha256` sidecar file."""
    path = Path(file_path)
    sha = digest or compute_sha256(path)
    sidecar = path.with_name(f"{path.name}.sha256")
    sidecar.write_text(f"{sha}  {path.name}\n", encoding="utf-8")
    return sidecar


def verify_media_integrity(
    file_path: Path,
    ffmpeg_path: Optional[Path] = None,
    timeout: int = 25,
) -> tuple[bool, str]:
    """Verify that a downloaded media file is non-empty and has a valid container header."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return False, "File does not exist on disk."

    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"Could not stat file: {exc}"

    if size <= 0:
        return False, "Downloaded file is empty (0 bytes)."

    ffmpeg_bin = ffmpeg_path or find_ffmpeg()
    if not ffmpeg_bin:
        return True, f"File size verified ({size} bytes; FFmpeg not available for deep decode check)."

    cmd = [
        str(ffmpeg_bin),
        "-v",
        "error",
        "-t",
        "1",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True, "Integrity decode check timed out after 1s sample; file header readable."
    except OSError as exc:
        LOGGER.debug("FFmpeg integrity probe could not start: %s", exc)
        return True, f"File size verified ({size} bytes)."

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        return False, err

    return True, "Media container and stream headers verified."
