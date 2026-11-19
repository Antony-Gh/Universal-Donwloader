"""URL normalization, network redirects, and platform/content type detection."""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from universal_downloader.models import ContentType, DetectedTarget, Platform

LOGGER = logging.getLogger("universal_downloader")

PLATFORM_DOMAINS: dict[Platform, tuple[str, ...]] = {
    Platform.YOUTUBE: (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    ),
    Platform.INSTAGRAM: (
        "instagram.com",
        "www.instagram.com",
    ),
    Platform.FACEBOOK: (
        "facebook.com",
        "www.facebook.com",
        "fb.watch",
        "web.facebook.com",
    ),
    Platform.THREADS: (
        "threads.net",
        "www.threads.net",
    ),
    Platform.TWITTER: (
        "twitter.com",
        "www.twitter.com",
        "x.com",
        "www.x.com",
    ),
    Platform.TIKTOK: (
        "tiktok.com",
        "www.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    ),
    Platform.REDDIT: (
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "redd.it",
    ),
    Platform.PINTEREST: (
        "pinterest.com",
        "www.pinterest.com",
        "pin.it",
    ),
    Platform.SNAPCHAT: (
        "snapchat.com",
        "www.snapchat.com",
    ),
    Platform.TELEGRAM: (
        "t.me",
        "telegram.me",
        "telegram.org",
    ),
    Platform.LINKEDIN: (
        "linkedin.com",
        "www.linkedin.com",
    ),
    Platform.WHATSAPP: (
        "whatsapp.com",
        "www.whatsapp.com",
    ),
    Platform.VIMEO: (
        "vimeo.com",
        "www.vimeo.com",
    ),
    Platform.TWITCH: (
        "twitch.tv",
        "www.twitch.tv",
    ),
    Platform.DAILYMOTION: (
        "dailymotion.com",
        "www.dailymotion.com",
        "dai.ly",
    ),
    Platform.SOUNDCLOUD: (
        "soundcloud.com",
        "www.soundcloud.com",
    ),
    Platform.BILIBILI: (
        "bilibili.com",
        "www.bilibili.com",
        "b23.tv",
    ),
    Platform.BLUESKY: (
        "bsky.app",
        "main.bsky.app",
    ),
    Platform.BANDCAMP: (
        "bandcamp.com",
    ),
    Platform.LOOM: (
        "loom.com",
        "www.loom.com",
    ),
}

TIKTOK_SHORT_DOMAINS = frozenset({"vt.tiktok.com", "vm.tiktok.com"})
TIKTOK_VIDEO_PATH_RE = re.compile(r"/video/\d+", re.IGNORECASE)
INSTAGRAM_MEDIA_PATH_RE = re.compile(r"/(?:reel|reels|p|tv)/[^/]+", re.IGNORECASE)

# Recognises every common YouTube video link form: youtu.be/ID, /embed/ID, /live/ID,
# /shorts/ID, /v/ID and ?v=ID / &v=ID (11-character IDs).
YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:embed/|live/|shorts/|v/)|[?&]v=)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
YOUTUBE_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DEEP_LINK_HASH_RE = re.compile(
    r"^#?(?P<id>[A-Za-z0-9_-]{11})(?:/(?P<format>[A-Za-z0-9]+))?$",
    re.IGNORECASE,
)
KNOWN_FORMAT_HINTS = {
    "mp3",
    "mp4",
    "audio",
    "video",
    "m4a",
    "flac",
    "opus",
    "wav",
    "aac",
    "best",
}


def parse_url_format_hint(raw: str) -> tuple[str, Optional[str]]:
    """Parse direct deep link format hashes (#ID/format, url#format, etc).

    Returns (cleaned_url, format_hint).
    """
    raw = (raw or "").strip()
    if not raw:
        return "", None

    # Pattern: #ID/format or #ID
    m = DEEP_LINK_HASH_RE.match(raw)
    if m:
        video_id = m.group("id")
        fmt = (m.group("format") or "").lower() or None
        return f"https://www.youtube.com/watch?v={video_id}", fmt

    if "#" in raw:
        base, _, fragment = raw.partition("#")
        base = base.strip()
        fragment = fragment.strip().lower()

        sub_m = DEEP_LINK_HASH_RE.match(fragment)
        if sub_m:
            vid = sub_m.group("id")
            fmt = (sub_m.group("format") or "").lower() or None
            return f"https://www.youtube.com/watch?v={vid}", fmt

        if fragment in KNOWN_FORMAT_HINTS:
            if YOUTUBE_BARE_ID_RE.match(base):
                base = f"https://www.youtube.com/watch?v={base}"
            return base, fragment

    return raw, None


def extract_youtube_video_id(value: str) -> Optional[str]:
    """Return the 11-character YouTube video ID found in a URL, or None."""
    if not value:
        return None
    match = YOUTUBE_VIDEO_ID_RE.search(value.strip())
    return match.group(1) if match else None


def canonical_youtube_url(value: str) -> Optional[str]:
    """Return https://www.youtube.com/watch?v=ID for any YouTube video link form.

    Tracking parameters (si, feature, pp, ...) are dropped. Links that carry a playlist
    (list=) are left untouched by callers so playlist downloads keep working.
    """
    video_id = extract_youtube_video_id(value)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_url(value: str) -> str:
    """Validate and normalize arbitrary URL inputs."""
    value = value.strip()

    if not value:
        raise ValueError("URL is empty.")

    if value.startswith("www."):
        value = "https://" + value

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value

    parsed = urllib.parse.urlparse(value)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not parsed.netloc:
        raise ValueError("URL does not contain a hostname.")

    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def get_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        return ""
    return parsed.hostname.lower().rstrip(".")


def resolve_url_redirect(url: str, timeout: int) -> str:
    """Follow HTTP redirects and return the final destination URL."""
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def normalize_tiktok_url(url: str, timeout: int = 30) -> str:
    """Resolve TikTok short links and strip noisy tracking parameters."""
    url = normalize_url(url)
    domain = get_domain(url)

    if domain in TIKTOK_SHORT_DOMAINS:
        try:
            url = normalize_url(resolve_url_redirect(url, timeout))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            LOGGER.debug("Could not resolve TikTok short URL: %s", exc)

    parsed = urllib.parse.urlparse(url)

    if TIKTOK_VIDEO_PATH_RE.search(parsed.path) and (
        parsed.query or parsed.fragment
    ):
        url = urllib.parse.urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.params,
                "",
                "",
            )
        )

    return url


def normalize_instagram_url(url: str) -> str:
    """Strip noisy tracking parameters (utm_source, igsh, srtk) from Instagram media URLs."""
    url = normalize_url(url)
    parsed = urllib.parse.urlparse(url)

    if INSTAGRAM_MEDIA_PATH_RE.search(parsed.path) and (parsed.query or parsed.fragment):
        path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
        url = urllib.parse.urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.params,
                "",
                "",
            )
        )

    return url


def normalize_youtube_url(url: str) -> str:
    """Canonicalise single-video YouTube links (youtu.be, shorts, embed, live, ?v=).

    Playlist links (list=) and channel/profile links are returned unchanged.
    """
    url = normalize_url(url)
    parsed = urllib.parse.urlparse(url)
    query = parsed.query.lower()

    if "list=" in query or "/playlist" in parsed.path.lower():
        return url

    canonical = canonical_youtube_url(url)
    return canonical or url


def domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith("." + candidate)


def detect_platform(url: str) -> Platform:
    try:
        normalized = normalize_url(url)
    except ValueError:
        return Platform.UNKNOWN

    domain = get_domain(normalized)

    for platform_name, domains in PLATFORM_DOMAINS.items():
        if any(domain_matches(domain, item) for item in domains):
            return platform_name

    return Platform.UNKNOWN


def detect_content_type(url: str, platform: Platform) -> ContentType:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower().rstrip("/")

    if platform == Platform.YOUTUBE:
        if "/playlist" in parsed.query.lower() or "list=" in parsed.query.lower():
            return ContentType.PLAYLIST

        if "/channel/" in path or "/@" in path or path.startswith("/c/"):
            return ContentType.PROFILE

        if "/shorts/" in path:
            return ContentType.VIDEO

        if "/watch" in path or parsed.netloc.endswith("youtu.be"):
            return ContentType.VIDEO

    if platform == Platform.INSTAGRAM:
        if re.search(r"/(reel|reels|tv)/", path):
            return ContentType.VIDEO
        if re.search(r"/(p|tv|reel)/", path):
            return ContentType.POST

        segments = [s for s in path.split("/") if s]
        if len(segments) == 1:
            return ContentType.PROFILE

    if platform == Platform.TIKTOK:
        domain = get_domain(url)
        if domain in {"vt.tiktok.com", "vm.tiktok.com"}:
            return ContentType.VIDEO

        if "/video/" in path:
            return ContentType.VIDEO

        if path.startswith("/@"):
            segments = [s for s in path.split("/") if s]
            if len(segments) == 1:
                return ContentType.PROFILE
            if len(segments) >= 3 and segments[1].lower() == "video":
                return ContentType.VIDEO

        return ContentType.UNKNOWN

    if platform == Platform.FACEBOOK:
        if "/watch" in path or "/reel" in path or "/videos/" in path or "/share/v/" in path or "/share/r/" in path:
            return ContentType.VIDEO
        if "/profile.php" in path or "/people/" in path:
            return ContentType.PROFILE
        fb_segments = [s for s in path.split("/") if s]
        fb_reserved = {
            "watch", "reel", "reels", "videos", "share", "story.php", "photo", "photo.php",
            "permalink.php", "groups", "events", "marketplace", "gaming", "login", "help",
            "pages", "hashtag", "posts", "stories", "live", "sharer",
        }
        if len(fb_segments) == 1 and fb_segments[0].lower() not in fb_reserved:
            return ContentType.PROFILE

    if platform == Platform.TWITTER:
        if "/status/" in path:
            return ContentType.POST
        if path.count("/") <= 2 and path:
            return ContentType.PROFILE

    if platform == Platform.REDDIT:
        if "/user/" in path or "/u/" in path:
            return ContentType.PROFILE
        if "/comments/" in path:
            return ContentType.POST

    if platform == Platform.THREADS:
        if "/post/" in path:
            return ContentType.POST
        if path.startswith("/@"):
            return ContentType.PROFILE

    if platform == Platform.BLUESKY:
        if "/post/" in path:
            return ContentType.POST
        if "/profile/" in path:
            return ContentType.PROFILE

    if platform == Platform.PINTEREST:
        if "/pin/" in path:
            return ContentType.POST

    if platform == Platform.VIMEO:
        if "/channels/" in path or "/user/" in path:
            return ContentType.PROFILE
        return ContentType.VIDEO

    if platform == Platform.TWITCH:
        if "/videos/" in path or "/clip/" in path or "/clips/" in path:
            return ContentType.VIDEO
        return ContentType.PROFILE

    if platform in (Platform.SOUNDCLOUD, Platform.BANDCAMP):
        return ContentType.AUDIO

    if platform in (Platform.DAILYMOTION, Platform.BILIBILI, Platform.LOOM):
        return ContentType.VIDEO

    return ContentType.UNKNOWN


def detect_target(url: str, timeout: int = 30) -> DetectedTarget:
    cleaned_url, format_hint = parse_url_format_hint(url)
    target_url = cleaned_url if cleaned_url else url

    normalized = normalize_url(target_url)
    platform = detect_platform(normalized)

    if platform == Platform.TIKTOK:
        normalized = normalize_tiktok_url(normalized, timeout=timeout)
    elif platform == Platform.INSTAGRAM:
        normalized = normalize_instagram_url(normalized)
    elif platform == Platform.YOUTUBE:
        normalized = normalize_youtube_url(normalized)

    content_type = detect_content_type(normalized, platform)

    return DetectedTarget(
        original_url=url,
        normalized_url=normalized,
        platform=platform,
        content_type=content_type,
        is_profile_candidate=content_type == ContentType.PROFILE,
        format_hint=format_hint,
    )
