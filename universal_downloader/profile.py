"""Public profile photo resolution and image extraction."""

from __future__ import annotations

import html
import logging
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from universal_downloader.console import info
from universal_downloader.exceptions import ExtractionError, ProfileError
from universal_downloader.extractor import YTDLPExtractor
from universal_downloader.models import AppConfig, Platform
from universal_downloader.utils.fs import (
    ensure_inside_directory,
    platform_directory,
    sanitize_filename,
    unique_path,
)
from universal_downloader.utils.net import detect_target, normalize_url

LOGGER = logging.getLogger("universal_downloader")

USERNAME_PLATFORM_PREFIXES = {
    "instagram": Platform.INSTAGRAM,
    "tiktok": Platform.TIKTOK,
    "twitter": Platform.TWITTER,
    "x": Platform.TWITTER,
    "threads": Platform.THREADS,
    "reddit": Platform.REDDIT,
    "youtube": Platform.YOUTUBE,
    "twitch": Platform.TWITCH,
    "soundcloud": Platform.SOUNDCLOUD,
    "bandcamp": Platform.BANDCAMP,
    "bluesky": Platform.BLUESKY,
}


def extract_username_from_profile_url(
    url: str,
    platform: Platform,
) -> Optional[str]:
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path:
        return None

    segments = [segment for segment in path.split("/") if segment]

    if platform == Platform.YOUTUBE:
        if segments[0].startswith("@"):
            return segments[0][1:]
        if segments[0] in {"channel", "c", "user"} and len(segments) > 1:
            return segments[-1]

    if platform in {
        Platform.INSTAGRAM,
        Platform.TIKTOK,
        Platform.TWITTER,
        Platform.THREADS,
        Platform.SOUNDCLOUD,
        Platform.TWITCH,
        Platform.BLUESKY,
    }:
        if segments:
            value = segments[0]
            if value.startswith("@"):
                value = value[1:]
            return value

    if platform == Platform.REDDIT:
        for prefix in ("user", "u"):
            if prefix in segments:
                index = segments.index(prefix)
                if index + 1 < len(segments):
                    return segments[index + 1]

    return None


def resolve_profile_input(value: str) -> str:
    value = value.strip()
    if not value:
        raise ProfileError("Profile value is empty.")

    if (
        "://" in value
        or value.startswith("www.")
        or "." in value.split("/")[0]
    ):
        return normalize_url(value)

    if value.startswith("@"):
        raise ProfileError(
            "A bare @username is ambiguous. "
            "Provide the platform profile URL, for example:\n"
            "  https://www.instagram.com/username/"
        )

    if ":" in value:
        prefix, username = value.split(":", 1)
        platform = USERNAME_PLATFORM_PREFIXES.get(prefix.strip().lower())

        if platform and username.strip():
            username = username.strip().lstrip("@")
            domain_map = {
                Platform.INSTAGRAM: "instagram.com",
                Platform.TIKTOK: "tiktok.com",
                Platform.TWITTER: "x.com",
                Platform.THREADS: "threads.net",
                Platform.REDDIT: "reddit.com/user",
                Platform.YOUTUBE: "youtube.com/@",
                Platform.TWITCH: "twitch.tv",
                Platform.SOUNDCLOUD: "soundcloud.com",
                Platform.BLUESKY: "bsky.app/profile",
            }

            domain = domain_map.get(platform, f"{prefix}.com")
            if platform == Platform.REDDIT or platform == Platform.BLUESKY:
                return normalize_url(f"https://{domain}/{username}")
            if platform == Platform.YOUTUBE:
                return normalize_url(f"https://{domain}{username}")
            return normalize_url(f"https://{domain}/{username}/")

    raise ProfileError(
        "A bare username is ambiguous. Use platform:username, for example:\n"
        "  instagram:username\n"
        "  tiktok:username\n"
        "  x:username\n"
        "or provide the complete public profile URL."
    )


def extract_meta_image(html_text: str) -> Optional[str]:
    patterns = [
        re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I),
        re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', re.I),
        re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I),
        re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image', re.I),
        re.compile(r'<link[^>]+rel=["\'](?:image_src|apple-touch-icon)["\'][^>]+href=["\']([^"\']+)', re.I),
    ]

    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            return html.unescape(match.group(1))

    return None


def fetch_public_html(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise ProfileError(f"Public profile page returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ProfileError(f"Could not access public profile page: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ProfileError("Profile request timed out.") from exc


def extract_thumbnail_candidates(info_data: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    direct_keys = (
        "avatar",
        "channel_thumbnail",
        "uploader_thumbnail",
        "creator_thumbnail",
        "thumbnail",
    )

    for key in direct_keys:
        value = info_data.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    thumbnails = info_data.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in sorted(
            (
                item
                for item in thumbnails
                if isinstance(item, dict) and item.get("url")
            ),
            key=lambda item: (
                item.get("width") or 0,
                item.get("height") or 0,
            ),
            reverse=True,
        ):
            url = item.get("url")
            if isinstance(url, str):
                candidates.append(url)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)

    return unique


def image_extension_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    suffix = Path(path).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    return suffix if suffix in allowed else ".jpg"


def download_public_image(
    image_url: str,
    destination: Path,
    timeout: int,
    base_dir: Path,
) -> Path:
    request = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = unique_path(destination)
    destination = ensure_inside_directory(base_dir, destination)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with temp_path.open("wb") as fh:
                shutil.copyfileobj(response, fh, length=1024 * 128)

        temp_path.replace(destination)
        return destination

    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class ProfilePhotoResolver:
    """Best-effort public profile image resolver."""

    def __init__(
        self,
        config: AppConfig,
        extractor: YTDLPExtractor,
    ) -> None:
        self.config = config
        self.extractor = extractor

    def resolve(
        self,
        profile_url: str,
        platform: Platform,
        username_hint: Optional[str] = None,
    ) -> Path:
        target = detect_target(profile_url, timeout=self.config.timeout)

        info(f"Platform: {platform.value}", self.config)
        info("Resolving publicly exposed profile image...", self.config)

        candidates: list[str] = []

        # 1. First attempt: yt-dlp metadata
        try:
            extracted = self.extractor.extract_info(
                target.normalized_url,
                download=False,
                extra={"skip_download": True, "extract_flat": True},
            )
            candidates.extend(extract_thumbnail_candidates(extracted))
        except ExtractionError as exc:
            LOGGER.info("yt-dlp profile metadata unavailable: %s", exc)

        # 2. Second attempt: public HTML metadata
        try:
            page = fetch_public_html(target.normalized_url, self.config.timeout)
            meta_image = extract_meta_image(page)
            if meta_image:
                candidates.append(
                    urllib.parse.urljoin(target.normalized_url, meta_image)
                )
        except ProfileError as exc:
            LOGGER.info("Public HTML profile lookup failed: %s", exc)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.startswith(("http://", "https://")) and candidate not in seen:
                seen.add(candidate)
                unique_candidates.append(candidate)

        if not unique_candidates:
            raise ProfileError(
                "No publicly exposed profile image could be resolved. "
                "The profile may require authentication or be private."
            )

        username = (
            username_hint
            or extract_username_from_profile_url(target.normalized_url, platform)
            or "profile"
        )

        filename = sanitize_filename(username, "profile") + (
            image_extension_from_url(unique_candidates[0])
        )

        destination_dir = (
            self.config.output_dir
            / platform_directory(platform)
            / "profile_pictures"
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / filename
        destination = ensure_inside_directory(self.config.output_dir, destination)

        for image_url in unique_candidates:
            try:
                return download_public_image(
                    image_url,
                    destination,
                    self.config.timeout,
                    self.config.output_dir,
                )
            except Exception as exc:
                LOGGER.info("Profile image candidate failed: %s", exc)

        raise ProfileError(
            "A public image URL was found, but it could not be downloaded."
        )
