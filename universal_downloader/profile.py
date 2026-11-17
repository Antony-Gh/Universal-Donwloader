"""Public and cookie-authorized profile photo resolution and image extraction."""

from __future__ import annotations

import html
import http.cookiejar
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
    "facebook": Platform.FACEBOOK,
    "fb": Platform.FACEBOOK,
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

GENERIC_LOGO_SUBSTRINGS = (
    "/rsrc.php/",
    "static.xx.fbcdn.net/rsrc",
    "static.cdninstagram.com/rsrc",
    "instagram.com/static/images/ico",
    "abs.twimg.com/responsive-web/client-web/icon",
    "favicon.ico",
    "apple-touch-icon",
    "fb_icon_325x325.png",
)


def is_generic_site_logo(url: str) -> bool:
    lowered = url.lower()
    return any(token in lowered for token in GENERIC_LOGO_SUBSTRINGS)


def load_cookie_jar(config: AppConfig) -> Optional[http.cookiejar.CookieJar]:
    """Load the user's configured cookies (cookies.txt or browser session) for authorized profile access."""
    if config.cookies_file and config.cookies_file.exists():
        jar = http.cookiejar.MozillaCookieJar(str(config.cookies_file))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
            return jar
        except Exception as exc:
            LOGGER.warning("Could not load cookies file %s: %s", config.cookies_file, exc)

    if config.cookies_from_browser:
        try:
            from yt_dlp.cookies import extract_cookies_from_browser

            return extract_cookies_from_browser(config.cookies_from_browser)
        except Exception as exc:
            LOGGER.warning("Could not load cookies from browser '%s': %s", config.cookies_from_browser, exc)

    return None


def _build_url_opener(cookie_jar: Optional[http.cookiejar.CookieJar]) -> urllib.request.OpenerDirector:
    if cookie_jar is not None:
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    return urllib.request.build_opener()


def extract_username_from_profile_url(
    url: str,
    platform: Platform,
) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return None

    segments = [segment for segment in path.split("/") if segment]

    if platform == Platform.FACEBOOK:
        if segments[0].lower() == "profile.php":
            qs = urllib.parse.parse_qs(parsed.query)
            profile_id = qs.get("id", [None])[0]
            return profile_id or "facebook_profile"
        return segments[0]

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
                Platform.FACEBOOK: "facebook.com",
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


def fetch_public_html(
    url: str,
    timeout: int,
    cookie_jar: Optional[http.cookiejar.CookieJar] = None,
) -> str:
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

    opener = _build_url_opener(cookie_jar)
    try:
        with opener.open(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise ProfileError(f"Profile page returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ProfileError(f"Could not access profile page: {exc.reason}") from exc
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
    cookie_jar: Optional[http.cookiejar.CookieJar] = None,
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

    opener = _build_url_opener(cookie_jar)
    try:
        with opener.open(request, timeout=timeout) as response:
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
    """Best-effort profile image resolver for public and cookie-authorized profiles."""

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
        cookie_jar = load_cookie_jar(self.config)

        info(f"Platform: {platform.value}", self.config)
        if cookie_jar is not None:
            info("Resolving profile image using your configured session cookies...", self.config)
        else:
            info("Resolving publicly exposed profile image...", self.config)

        candidates: list[str] = []

        # 1. First attempt: yt-dlp metadata (automatically uses configured cookies)
        try:
            extracted = self.extractor.extract_info(
                target.normalized_url,
                download=False,
                extra={"skip_download": True, "extract_flat": True},
            )
            candidates.extend(extract_thumbnail_candidates(extracted))
        except ExtractionError as exc:
            LOGGER.info("yt-dlp profile metadata unavailable: %s", exc)

        # 2. Second attempt: standard profile page HTML metadata (public or user-authenticated)
        try:
            page = fetch_public_html(target.normalized_url, self.config.timeout, cookie_jar=cookie_jar)
            meta_image = extract_meta_image(page)
            if meta_image:
                candidates.append(
                    urllib.parse.urljoin(target.normalized_url, meta_image)
                )
        except ProfileError as exc:
            LOGGER.info("Profile HTML lookup failed: %s", exc)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if (
                candidate.startswith(("http://", "https://"))
                and candidate not in seen
                and not is_generic_site_logo(candidate)
            ):
                seen.add(candidate)
                unique_candidates.append(candidate)

        if not unique_candidates:
            if cookie_jar is not None:
                raise ProfileError(
                    "No profile picture could be resolved with your current session cookies. "
                    "The account may be private/locked to accounts without permission, or cookies may need refreshing."
                )
            raise ProfileError(
                "No publicly exposed profile image could be resolved. "
                "If your account is authorized to view this profile, select Browser Cookies or import cookies.txt and try again."
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
                    cookie_jar=cookie_jar,
                )
            except Exception as exc:
                LOGGER.info("Profile image candidate failed: %s", exc)

        raise ProfileError(
            "A profile image URL was found, but it could not be downloaded."
        )
