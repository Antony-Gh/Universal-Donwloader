"""Filesystem helpers, filename sanitization, and path safety checks."""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from universal_downloader.exceptions import DownloadError
from universal_downloader.models import Platform

LOGGER = logging.getLogger("universal_downloader")

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """Sanitize arbitrary strings into safe filesystem basenames."""
    name = html.unescape(name or "")
    name = INVALID_FILENAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")

    if not name:
        name = fallback

    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = "_" + name

    return name[:180].rstrip(" .") or fallback


def ensure_inside_directory(base: Path, candidate: Path) -> Path:
    """Enforce that candidate path stays securely inside base directory."""
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()

    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise DownloadError(
            f"Security violation: path {candidate} escaped boundary {base}."
        ) from exc

    return candidate_resolved


def unique_path(path: Path) -> Path:
    """Return non-colliding path by incrementing numeric suffix if needed."""
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for index in range(1, 100000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate

    raise DownloadError(f"Could not create a unique filename for: {path.name}")


def platform_directory(platform: Platform) -> str:
    if platform == Platform.TWITTER:
        return "twitter"
    return platform.value


def safe_json_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple)):
        return [safe_json_value(item) for item in value]

    if isinstance(value, dict):
        return {str(key): safe_json_value(val) for key, val in value.items()}

    return str(value)


def compact_metadata(info: dict[str, Any], original_url: str) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "description",
        "uploader",
        "uploader_id",
        "channel",
        "channel_id",
        "creator",
        "webpage_url",
        "upload_date",
        "timestamp",
        "duration",
        "width",
        "height",
        "fps",
        "ext",
        "format_id",
        "format",
        "resolution",
        "thumbnail",
        "playlist",
        "playlist_index",
        "playlist_title",
        "categories",
        "tags",
    )

    result: dict[str, Any] = {
        "original_url": original_url,
    }

    for key in keys:
        if key in info and info[key] is not None:
            result[key] = safe_json_value(info[key])

    return result


def write_metadata_file(
    path: Path,
    info: dict[str, Any],
    original_url: str,
) -> Optional[Path]:
    metadata = compact_metadata(info, original_url)
    metadata_path = path.with_suffix(path.suffix + ".json")

    try:
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata_path
    except OSError:
        LOGGER.exception("Unable to write metadata: %s", metadata_path)
        return None


def preferred_media_filename(info: dict[str, Any]) -> Optional[str]:
    """Build uploader_uploader_id_id.ext from download metadata."""
    media_id = info.get("id")
    if media_id is None:
        return None

    uploader = sanitize_filename(
        str(info.get("uploader") or "unknown"),
        "unknown",
    )
    uploader_id = sanitize_filename(
        str(info.get("uploader_id") or "unknown"),
        "unknown",
    )
    video_id = sanitize_filename(str(media_id), "unknown")
    extension = str(info.get("ext") or "mp4").lstrip(".")

    return f"{uploader}_{uploader_id}_{video_id}.{extension}"


def rename_media_file(
    path: Path,
    info: dict[str, Any],
    base_dir: Path,
) -> Path:
    """Rename a downloaded file to metadata-based filename if appropriate."""
    preferred_name = preferred_media_filename(info)
    if not preferred_name:
        return path

    destination = ensure_inside_directory(
        base_dir,
        path.parent / preferred_name,
    )
    destination = unique_path(destination)

    if path.resolve() == destination.resolve():
        return path

    metadata_path = path.with_suffix(path.suffix + ".json")
    path.replace(destination)

    if metadata_path.exists():
        metadata_destination = destination.with_suffix(
            destination.suffix + ".json"
        )
        metadata_path.replace(unique_path(metadata_destination))

    return destination
