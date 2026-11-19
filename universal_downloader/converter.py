"""Direct local media converter and audio extractor powered by FFmpeg.

Allows converting local video/audio files (e.g. extracting MP3 from MP4/MKV or
remuxing MKV/AVI into MP4) using the bundled or system FFmpeg binary without
requiring external tools or yt-dlp.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from universal_downloader.exceptions import DependencyError, DownloadError
from universal_downloader.ffmpeg_manager import ensure_ffmpeg, find_ffmpeg
from universal_downloader.utils.fs import unique_path

LOGGER = logging.getLogger("universal_downloader")

AUDIO_FORMATS = {"mp3", "m4a", "flac", "opus", "wav", "aac"}
VIDEO_FORMATS = {"mp4", "mkv", "mov", "webm"}
SUPPORTED_FORMATS = AUDIO_FORMATS | VIDEO_FORMATS


def build_ffmpeg_convert_cmd(
    ffmpeg_bin: Path,
    input_path: Path,
    output_path: Path,
    target_format: str,
    *,
    audio_quality: str = "192k",
    remux_only: bool = False,
) -> list[str]:
    """Build a safe argv list for FFmpeg conversion or lossless container remuxing."""
    fmt = (target_format or "").strip().lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported target format '{target_format}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}."
        )

    cmd: list[str] = [
        str(ffmpeg_bin),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-map_metadata",
        "0",
    ]

    if fmt in AUDIO_FORMATS:
        cmd.append("-vn")
        if fmt == "mp3":
            cmd.extend(["-c:a", "libmp3lame", "-b:a", audio_quality])
        elif fmt in {"m4a", "aac"}:
            cmd.extend(["-c:a", "aac", "-b:a", audio_quality])
        elif fmt == "flac":
            cmd.extend(["-c:a", "flac"])
        elif fmt == "opus":
            cmd.extend(["-c:a", "libopus", "-b:a", audio_quality])
        elif fmt == "wav":
            cmd.extend(["-c:a", "pcm_s16le"])
    else:
        if remux_only:
            cmd.extend(["-c", "copy"])
        elif fmt == "webm":
            cmd.extend(["-c:v", "libvpx-vp9", "-c:a", "libopus", "-b:a", audio_quality])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", audio_quality])

        if fmt in {"mp4", "mov"}:
            cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(output_path))
    return cmd


def convert_media_file(
    input_path: Path,
    target_format: str,
    *,
    output_dir: Optional[Path] = None,
    audio_quality: str = "192k",
    remux_only: bool = False,
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    """Convert or remux a local media file into ``target_format`` using FFmpeg."""
    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input media file not found: {src}")

    fmt = (target_format or "").strip().lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported target format '{target_format}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}."
        )

    ffmpeg_bin = ffmpeg_path or find_ffmpeg() or ensure_ffmpeg(auto_download=False)
    if not ffmpeg_bin:
        raise DependencyError(
            "FFmpeg is required for local media conversion but was not found on PATH or in local cache."
        )

    dest_dir = Path(output_dir).expanduser() if output_dir else src.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_path(dest_dir / f"{src.stem}.{fmt}")

    cmd = build_ffmpeg_convert_cmd(
        ffmpeg_bin,
        src,
        output_path,
        fmt,
        audio_quality=audio_quality,
        remux_only=remux_only,
    )
    LOGGER.debug("Running FFmpeg convert command: %s", cmd)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise DownloadError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        err_detail = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        raise DownloadError(f"Media conversion failed: {err_detail}")

    return output_path.resolve()
