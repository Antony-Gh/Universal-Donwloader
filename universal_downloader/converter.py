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
    normalize_audio: bool = False,
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
        if normalize_audio:
            cmd.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])
    else:
        if remux_only:
            cmd.extend(["-c", "copy"])
        elif fmt == "webm":
            cmd.extend(["-c:v", "libvpx-vp9", "-c:a", "libopus", "-b:a", audio_quality])
            if normalize_audio:
                cmd.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", audio_quality])
            if normalize_audio:
                cmd.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])

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
    normalize_audio: bool = False,
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
        normalize_audio=normalize_audio,
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


def build_ffmpeg_gif_cmd(
    ffmpeg_bin: Path,
    input_path: Path,
    output_path: Path,
    *,
    start_time: Optional[str] = None,
    duration: Optional[str] = None,
    fps: int = 15,
    width: int = 480,
) -> list[str]:
    """Build FFmpeg command for two-pass palette-optimized animated GIF generation."""
    cmd: list[str] = [
        str(ffmpeg_bin),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if start_time:
        cmd.extend(["-ss", str(start_time)])
    if duration:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-i", str(input_path)])

    vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5"
    cmd.extend(["-filter_complex", vf, str(output_path)])
    return cmd


def video_to_gif(
    input_path: Path,
    output_path: Optional[Path] = None,
    *,
    start_time: Optional[str] = None,
    duration: Optional[str] = None,
    fps: int = 15,
    width: int = 480,
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    """Convert input video into a high-quality animated GIF using FFmpeg."""
    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input media file not found: {src}")

    ffmpeg_bin = ffmpeg_path or find_ffmpeg() or ensure_ffmpeg(auto_download=False)
    if not ffmpeg_bin:
        raise DependencyError("FFmpeg is required for GIF generation but was not found on PATH or in cache.")

    dest = output_path or unique_path(src.parent / f"{src.stem}.gif")
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_gif_cmd(
        ffmpeg_bin,
        src,
        dest,
        start_time=start_time,
        duration=duration,
        fps=fps,
        width=width,
    )
    LOGGER.debug("Running FFmpeg GIF command: %s", cmd)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DownloadError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise DownloadError(f"GIF generation failed: {err}")

    return dest.resolve()


def build_ffmpeg_frame_cmd(
    ffmpeg_bin: Path,
    input_path: Path,
    output_path: Path,
    *,
    timestamp: str = "00:00:01",
) -> list[str]:
    """Build FFmpeg command to capture a single frame at a specific timestamp."""
    return [
        str(ffmpeg_bin),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(timestamp),
        "-i",
        str(input_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]


def extract_frame(
    input_path: Path,
    output_path: Optional[Path] = None,
    *,
    timestamp: str = "00:00:01",
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    """Capture a single frame from video at timestamp and save as an image."""
    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input media file not found: {src}")

    ffmpeg_bin = ffmpeg_path or find_ffmpeg() or ensure_ffmpeg(auto_download=False)
    if not ffmpeg_bin:
        raise DependencyError("FFmpeg is required for frame extraction but was not found on PATH or in cache.")

    dest = output_path or unique_path(src.parent / f"{src.stem}_frame.png")
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_frame_cmd(ffmpeg_bin, src, dest, timestamp=timestamp)
    LOGGER.debug("Running FFmpeg frame capture command: %s", cmd)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DownloadError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise DownloadError(f"Frame extraction failed: {err}")

    return dest.resolve()


def build_ffmpeg_clip_cmd(
    ffmpeg_bin: Path,
    input_path: Path,
    output_path: Path,
    *,
    start_time: str,
    end_time: Optional[str] = None,
    duration: Optional[str] = None,
    copy_codec: bool = True,
) -> list[str]:
    """Build FFmpeg command to extract a media clip."""
    cmd: list[str] = [
        str(ffmpeg_bin),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start_time),
    ]
    if end_time:
        cmd.extend(["-to", str(end_time)])
    elif duration:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-i", str(input_path)])

    if copy_codec:
        cmd.extend(["-c", "copy"])
    else:
        cmd.extend(["-c:v", "libx264", "-c:a", "aac"])

    cmd.append(str(output_path))
    return cmd


def create_clip(
    input_path: Path,
    output_path: Optional[Path] = None,
    *,
    start_time: str,
    end_time: Optional[str] = None,
    duration: Optional[str] = None,
    copy_codec: bool = True,
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    """Extract a time-range clip from a media file."""
    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input media file not found: {src}")

    ffmpeg_bin = ffmpeg_path or find_ffmpeg() or ensure_ffmpeg(auto_download=False)
    if not ffmpeg_bin:
        raise DependencyError("FFmpeg is required for clip extraction but was not found on PATH or in cache.")

    dest = output_path or unique_path(src.parent / f"{src.stem}_clip{src.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_clip_cmd(
        ffmpeg_bin,
        src,
        dest,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        copy_codec=copy_codec,
    )
    LOGGER.debug("Running FFmpeg clip extraction command: %s", cmd)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DownloadError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise DownloadError(f"Clip extraction failed: {err}")

    return dest.resolve()
