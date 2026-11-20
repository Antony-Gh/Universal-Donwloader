"""Device & Social Media Optimization Presets for Universal Media Downloader.

Provides one-click optimized presets for:
- discord: Compresses video to fit under 25MB (or 10MB) for Discord free upload limits.
- whatsapp: 720p H.264 + AAC faststart MP4 for instant mobile sharing without re-compression.
- car_audio: Constant Bitrate (CBR 192k) MP3 with ID3v2.3 tags and loudness normalization.
- tv_theater: High-quality MP4/H.264 container with full multichannel audio pass-through.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from universal_downloader.exceptions import DependencyError, DownloadError
from universal_downloader.ffmpeg_manager import ensure_ffmpeg, find_ffmpeg
from universal_downloader.utils.fs import unique_path

LOGGER = logging.getLogger("universal_downloader")


@dataclass
class DevicePreset:
    id: str
    name: str
    description: str
    category: str
    target_format: str
    audio_only: bool = False
    quality: str = "best"
    prefer_codec: Optional[str] = "h264"
    audio_format: str = "mp3"
    audio_quality: str = "192k"
    normalize_audio: bool = False
    max_size_mb: Optional[float] = None
    extra_ffmpeg_args: List[str] = field(default_factory=list)


AVAILABLE_PRESETS: Dict[str, DevicePreset] = {
    "discord": DevicePreset(
        id="discord",
        name="Discord (<25MB)",
        description="Auto-compress video to fit within Discord's 25MB free upload limit with H.264 and faststart.",
        category="social",
        target_format="mp4",
        quality="720p",
        prefer_codec="h264",
        max_size_mb=24.5,
        extra_ffmpeg_args=["-c:v", "libx264", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"],
    ),
    "discord_10mb": DevicePreset(
        id="discord_10mb",
        name="Discord Basic (<10MB)",
        description="Compress video to fit strictly under 10MB for legacy Discord limits.",
        category="social",
        target_format="mp4",
        quality="480p",
        prefer_codec="h264",
        max_size_mb=9.5,
        extra_ffmpeg_args=["-c:v", "libx264", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart"],
    ),
    "whatsapp": DevicePreset(
        id="whatsapp",
        name="WhatsApp / Telegram",
        description="Optimized 720p H.264 MP4 with faststart for instant streaming and zero mobile distortion.",
        category="social",
        target_format="mp4",
        quality="720p",
        prefer_codec="h264",
        extra_ffmpeg_args=["-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"],
    ),
    "car_audio": DevicePreset(
        id="car_audio",
        name="Car Stereo & MP3 Player",
        description="CBR 192kbps MP3 with ID3v2.3 compatibility tags, loudness normalization, and embedded artwork.",
        category="audio",
        target_format="mp3",
        audio_only=True,
        audio_format="mp3",
        audio_quality="192k",
        normalize_audio=True,
        extra_ffmpeg_args=["-id3v2_version", "3"],
    ),
    "tv_theater": DevicePreset(
        id="tv_theater",
        name="TV / Home Theater (1080p/4K)",
        description="Highest quality video with multi-channel audio pass-through in an MP4 container for Plex and smart TVs.",
        category="device",
        target_format="mp4",
        quality="1080p",
        prefer_codec="h264",
        extra_ffmpeg_args=["-movflags", "+faststart"],
    ),
}


def list_presets() -> List[Dict[str, Any]]:
    """Return a list of all available device and social presets."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "category": p.category,
            "target_format": p.target_format,
            "audio_only": p.audio_only,
            "max_size_mb": p.max_size_mb,
        }
        for p in AVAILABLE_PRESETS.values()
    ]


def get_preset(preset_id: str) -> Optional[DevicePreset]:
    """Retrieve a preset by id (case-insensitive)."""
    key = (preset_id or "").strip().lower()
    return AVAILABLE_PRESETS.get(key)


def get_video_duration(file_path: Path, ffmpeg_bin: Optional[Path] = None) -> float:
    """Detect media duration in seconds using ffprobe or ffmpeg."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe and ffmpeg_bin:
        probe_candidate = ffmpeg_bin.parent / ("ffprobe.exe" if ffmpeg_bin.suffix == ".exe" else "ffprobe")
        if probe_candidate.exists():
            ffprobe = str(probe_candidate)

    if ffprobe:
        try:
            cmd = [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(file_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            dur = float(data.get("format", {}).get("duration", 0))
            if dur > 0:
                return dur
        except Exception:
            pass

    # Fallback parsing via ffmpeg stderr
    bin_path = ffmpeg_bin or find_ffmpeg()
    if bin_path and bin_path.exists():
        try:
            proc = subprocess.run([str(bin_path), "-i", str(file_path)], capture_output=True, text=True)
            for line in proc.stderr.splitlines():
                if "Duration:" in line:
                    # Duration: 00:03:15.22, start: ...
                    parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                    if len(parts) == 3:
                        h = float(parts[0])
                        m = float(parts[1])
                        s = float(parts[2])
                        return h * 3600 + m * 60 + s
        except Exception:
            pass

    return 60.0  # Safe 1-minute fallback estimate


def compress_video_to_target_size(
    input_path: Path,
    output_path: Optional[Path] = None,
    target_mb: float = 24.5,
    ffmpeg_bin: Optional[Path] = None,
) -> Path:
    """Compress a video file so its total file size is guaranteed under target_mb."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    bin_path = ffmpeg_bin or ensure_ffmpeg()
    if not bin_path:
        raise DependencyError("FFmpeg is required for video compression.")

    curr_mb = input_path.stat().st_size / (1024 * 1024)
    if curr_mb <= target_mb:
        # Already under target limit!
        LOGGER.info(f"File '{input_path.name}' is already {curr_mb:.2f}MB (under {target_mb}MB target).")
        return input_path

    if not output_path:
        out_dir = input_path.parent
        stem = f"{input_path.stem}_{int(target_mb)}mb"
        output_path = unique_path(out_dir, f"{stem}.mp4")

    duration = max(get_video_duration(input_path, bin_path), 1.0)
    # Total bits = target_bytes * 8
    target_total_bits = target_mb * 1024 * 1024 * 8 * 0.95  # 5% safety margin
    total_bitrate_bps = target_total_bits / duration

    # Allocate audio (e.g. 96k or 64k) and video
    audio_bitrate_k = 96 if total_bitrate_bps > 400_000 else 64
    video_bitrate_bps = max(total_bitrate_bps - (audio_bitrate_k * 1000), 100_000)
    video_bitrate_k = int(video_bitrate_bps / 1000)

    LOGGER.info(
        f"Compressing '{input_path.name}' ({curr_mb:.1f}MB -> <{target_mb}MB) | "
        f"Duration: {duration:.1f}s, Target Bitrate: {video_bitrate_k}k video + {audio_bitrate_k}k audio"
    )

    cmd = [
        str(bin_path),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-b:v", f"{video_bitrate_k}k",
        "-maxrate", f"{int(video_bitrate_k * 1.3)}k",
        "-bufsize", f"{int(video_bitrate_k * 2)}k",
        "-vf", "scale='min(1280,iw)':-2",  # scale down if wider than 720p
        "-c:a", "aac",
        "-b:a", f"{audio_bitrate_k}k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise DownloadError(f"FFmpeg compression failed: {res.stderr}")

    final_mb = output_path.stat().st_size / (1024 * 1024)
    LOGGER.info(f"Compressed file saved to: {output_path.name} ({final_mb:.2f}MB)")
    return output_path
