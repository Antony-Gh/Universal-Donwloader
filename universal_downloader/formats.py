"""Format inspection, parsing, and yt-dlp selector generation."""

from __future__ import annotations

import re
from typing import Any, Iterable

from universal_downloader.console import warning
from universal_downloader.exceptions import ConfigurationError
from universal_downloader.models import AppConfig, FormatInfo
from universal_downloader.progress import human_size


def parse_format(info: dict[str, Any]) -> list[FormatInfo]:
    formats = info.get("formats") or []
    result: list[FormatInfo] = []

    for fmt in formats:
        if not isinstance(fmt, dict):
            continue

        height = fmt.get("height")
        width = fmt.get("width")

        try:
            height = int(height) if height is not None else None
        except (ValueError, TypeError):
            height = None

        try:
            width = int(width) if width is not None else None
        except (ValueError, TypeError):
            width = None

        filesize = fmt.get("filesize") or fmt.get("filesize_approx")

        try:
            filesize = int(filesize) if filesize else None
        except (ValueError, TypeError):
            filesize = None

        fps = fmt.get("fps")

        try:
            fps = float(fps) if fps is not None else None
        except (ValueError, TypeError):
            fps = None

        resolution = fmt.get("resolution")

        if not resolution:
            if width and height:
                resolution = f"{width}x{height}"
            elif height:
                resolution = f"{height}p"
            else:
                resolution = "audio" if fmt.get("vcodec") == "none" else "unknown"

        result.append(
            FormatInfo(
                format_id=str(fmt.get("format_id", "")),
                extension=str(fmt.get("ext") or ""),
                resolution=str(resolution),
                height=height,
                width=width,
                fps=fps,
                filesize=filesize,
                vcodec=str(fmt.get("vcodec") or "none"),
                acodec=str(fmt.get("acodec") or "none"),
                format_note=str(fmt.get("format_note") or ""),
                raw=fmt,
            )
        )

    return result


def format_sort_key(fmt: FormatInfo) -> tuple:
    return (
        fmt.height or 0,
        1 if fmt.has_audio else 0,
        1 if fmt.has_video else 0,
        fmt.filesize or 0,
    )


def unique_video_heights(formats: Iterable[FormatInfo]) -> list[int]:
    heights = {
        fmt.height for fmt in formats if fmt.has_video and fmt.height
    }
    return sorted(heights, reverse=True)


def print_formats(info: dict[str, Any], config: AppConfig) -> None:
    formats = parse_format(info)

    if not formats:
        warning("No explicit formats were exposed by the extractor.", config)
        return

    print()
    print("Available formats:")
    print("-" * 95)
    print(
        f"{'ID':<10}"
        f"{'EXT':<7}"
        f"{'RESOLUTION':<15}"
        f"{'FPS':<8}"
        f"{'SIZE':<14}"
        f"{'VIDEO':<10}"
        f"{'AUDIO':<10}"
        f"NOTE"
    )
    print("-" * 95)

    seen: set[tuple] = set()

    for fmt in sorted(formats, key=format_sort_key, reverse=True):
        key = (
            fmt.format_id,
            fmt.extension,
            fmt.resolution,
            fmt.vcodec,
            fmt.acodec,
        )

        if key in seen:
            continue

        seen.add(key)

        print(
            f"{fmt.format_id:<10.10}"
            f"{fmt.extension:<7.7}"
            f"{fmt.resolution:<15.15}"
            f"{str(fmt.fps or ''):<8.8}"
            f"{human_size(fmt.filesize):<14.14}"
            f"{fmt.vcodec:<10.10}"
            f"{fmt.acodec:<10.10}"
            f"{fmt.format_note}"
        )

    print("-" * 95)


def quality_to_selector(
    quality: str,
    audio_only: bool,
    prefer_codec: Optional[str] = None,
) -> str:
    quality = quality.strip().lower()

    if audio_only or quality in {"audio", "audio-only"}:
        return "bestaudio/best"

    codec_clause = ""
    if prefer_codec:
        codec_lower = prefer_codec.strip().lower()
        if codec_lower in {"h264", "avc", "avc1"}:
            codec_clause = "[vcodec^=avc1]"
        elif codec_lower in {"vp9", "vp09"}:
            codec_clause = "[vcodec^=vp9]"
        elif codec_lower in {"av1", "av01"}:
            codec_clause = "[vcodec^=av01]"
        elif codec_lower in {"hevc", "h265"}:
            codec_clause = "[vcodec^=hev1]"

    if quality in {"best", "maximum", "max"}:
        if codec_clause:
            return f"bestvideo*{codec_clause}+bestaudio/bestvideo*+bestaudio/best"
        return "bestvideo*+bestaudio/best"

    match = re.fullmatch(r"(\d{3,4})p", quality)

    if match:
        height = int(match.group(1))
        if codec_clause:
            return (
                f"bestvideo*{codec_clause}[height<={height}]+bestaudio/"
                f"bestvideo*[height<={height}]+bestaudio/"
                f"best[height<={height}]/best"
            )
        return (
            f"bestvideo*[height<={height}]+bestaudio/"
            f"best[height<={height}]/best"
        )

    # Accept an explicit yt-dlp format selector.
    if re.fullmatch(r"[\w\-\+\*/\[\]=<>.,]+", quality):
        return quality

    raise ConfigurationError(
        f"Invalid quality value: {quality}\n"
        "Examples: best, 2160p, 1440p, 1080p, 720p, 480p, audio"
    )
