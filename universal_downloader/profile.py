"""Public and cookie-authorized profile photo resolution and image extraction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import html
import http.cookiejar
import io
import json
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


def _unescape_embedded_url(raw: str) -> str:
    cleaned = raw.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=")
    return html.unescape(cleaned).strip()


def upgrade_public_avatar_url(url: str) -> list[str]:
    """
    Return highest-resolution standard public CDN renditions first for known avatar URL patterns,
    followed by the original URL as fallback.
    """
    variants: list[str] = []
    lowered = url.lower()

    # X / Twitter: replace _normal (48x48) or _bigger (73x73) with original & _400x400
    if "pbs.twimg.com/profile_images/" in lowered:
        for suffix in ("_normal.", "_bigger.", "_mini.", "_200x200."):
            if suffix in url:
                variants.append(url.replace(suffix, "."))
                variants.append(url.replace(suffix, "_400x400."))
                break

    # YouTube / Google CDN: upgrade =s88 / =s176 / =s240 avatars to =s1024
    if ("yt3.googleusercontent.com" in lowered or "yt3.ggpht.com" in lowered) and re.search(r"=s\d{2,3}(?=[-&]|$)", url):
        variants.append(re.sub(r"=s\d{2,3}(?=[-&]|$)", "=s1024", url))

    variants.append(url)
    return list(dict.fromkeys(variants))


def estimate_image_resolution_score(url: str) -> tuple[int, int, int]:
    """
    Rank public profile image URLs so the highest-resolution avatar rendition sorts first.
    Returns (bucket_priority, resolution_tier, estimated_max_dimension).
    """
    lowered = url.lower()

    is_fb_avatar_bucket = "/t39.30808-1/" in lowered or "/t1.6435-1/" in lowered
    is_fb_cover_bucket = "/t39.30808-6/" in lowered

    # Extract explicit pixel dimension hints (mx877x858, s960x960, p720x720, s160x160, etc.)
    dims: list[int] = []
    for match in re.finditer(r"(?:^|[&/?_=.,-])(?:mx|s|p|w)(\d{2,4})x(\d{2,4})", lowered):
        dims.append(max(int(match.group(1)), int(match.group(2))))

    # YouTube / Google CDN =s1024 / =s176 / =s88
    for match in re.finditer(r"=[sw](\d{2,4})(?:[-&#]|$)", lowered):
        dims.append(int(match.group(1)))

    # X / Twitter size tokens
    if "pbs.twimg.com/profile_images/" in lowered:
        if "_normal." in lowered or "_mini." in lowered:
            dims.append(48)
        elif "_bigger." in lowered:
            dims.append(73)
        elif "_200x200." in lowered:
            dims.append(200)
        elif "_400x400." in lowered:
            dims.append(400)
        else:
            dims.append(1080)

    # Prefer dedicated avatar buckets over generic cover photos
    bucket_priority = 2 if is_fb_avatar_bucket else (0 if is_fb_cover_bucket else 1)

    if dims:
        max_dim = max(dims)
        tier = 3 if max_dim >= 600 else (2 if max_dim >= 300 else 1)
        return (bucket_priority, tier, max_dim)

    # Unscaled CDN image without small resize flags (e.g. full HD IG/FB/TikTok avatar)
    return (bucket_priority, 3, 1080)


def extract_profile_title(html_text: str) -> Optional[str]:
    for pattern in (
        re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I),
        re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', re.I),
        re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S),
    ):
        match = pattern.search(html_text)
        if match:
            title = html.unescape(match.group(1)).strip()
            if title:
                return title
    return None


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


@dataclass
class ProfileImageCandidate:
    url: str
    label: str = "Profile Picture"
    is_cover: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    filesize: Optional[int] = None
    ext: str = "jpg"
    verified: bool = False
    enhance_hd: bool = False

    @property
    def pixel_area(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return 0

    def to_format_dict(self, index: int) -> dict[str, Any]:
        resolution = f"{self.width}x{self.height}" if (self.width and self.height) else "Image"
        return {
            "format_id": f"img_hd_{index}" if self.enhance_hd else f"img_{index}",
            "ext": self.ext.lstrip(".") or "jpg",
            "resolution": resolution,
            "width": self.width,
            "height": self.height,
            "fps": None,
            "filesize": self.filesize,
            "vcodec": "image",
            "acodec": "none",
            "format_note": self.label,
            "url": self.url,
        }


def compute_hd_target_dimensions(width: int, height: int, target_min_side: int = 960, max_scale: float = 4.0) -> tuple[int, int]:
    """Calculate aspect-preserving HD target dimensions (up to 4x, aiming for >=960px on the longest side)."""
    longest = max(width, height)
    if longest <= 0 or longest >= target_min_side:
        return width, height
    scale = min(max_scale, target_min_side / float(longest))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def enhance_image_bytes_to_hd(
    data: bytes,
    target_min_side: int = 960,
    output_format: str = "PNG",
) -> tuple[bytes, int, int, str]:
    """
    Enhance a low-resolution profile image to crisp HD using progressive multi-step Lanczos3
    resampling, light deblocking, and edge-preserving unsharp masking (thresholded so smooth
    regions stay clean without noise or halos).
    Returns (enhanced_bytes, new_width, new_height, ext_without_dot).
    """
    from PIL import Image, ImageEnhance, ImageFilter

    with Image.open(io.BytesIO(data)) as raw_img:
        has_alpha = raw_img.mode in ("RGBA", "LA") or (raw_img.mode == "P" and "transparency" in raw_img.info)
        img = raw_img.convert("RGBA" if has_alpha else "RGB")
        orig_w, orig_h = img.size
        target_w, target_h = compute_hd_target_dimensions(orig_w, orig_h, target_min_side=target_min_side)

        if target_w <= orig_w and target_h <= orig_h:
            buf = io.BytesIO()
            if has_alpha or output_format.upper() == "PNG":
                img.save(buf, format="PNG", optimize=True)
                return buf.getvalue(), orig_w, orig_h, "png"
            img.save(buf, format="JPEG", quality=96, subsampling=0)
            return buf.getvalue(), orig_w, orig_h, "jpg"

        # 1. Light JPEG deblocking blend before upscaling (keeps details intact while softening 8x8 blocks)
        smooth_base = img.filter(ImageFilter.SMOOTH)
        work = Image.blend(img, smooth_base, alpha=0.14)

        # 2. Progressive multi-step Lanczos3 upscaling (max 1.5x per pass prevents stair-stepping)
        cur_w, cur_h = orig_w, orig_h
        resampler = getattr(Image, "Resampling", Image).LANCZOS
        while cur_w < target_w or cur_h < target_h:
            next_w = min(target_w, max(cur_w + 1, int(round(cur_w * 1.5))))
            next_h = min(target_h, max(cur_h + 1, int(round(cur_h * 1.5))))
            work = work.resize((next_w, next_h), resampler)
            cur_w, cur_h = next_w, next_h

        # 3. Edge-preserving Unsharp Mask (threshold=4 sharpens real contours without amplifying flat-area noise)
        if has_alpha:
            rgb_part = work.convert("RGB")
            alpha_ch = work.getchannel("A")
            rgb_part = rgb_part.filter(ImageFilter.UnsharpMask(radius=1.35, percent=115, threshold=4))
            rgb_part = ImageEnhance.Contrast(rgb_part).enhance(1.04)
            rgb_part = ImageEnhance.Sharpness(rgb_part).enhance(1.06)
            work = rgb_part.convert("RGBA")
            work.putalpha(alpha_ch)
        else:
            work = work.filter(ImageFilter.UnsharpMask(radius=1.35, percent=115, threshold=4))
            work = ImageEnhance.Contrast(work).enhance(1.04)
            work = ImageEnhance.Sharpness(work).enhance(1.06)

        buf = io.BytesIO()
        if has_alpha or output_format.upper() == "PNG":
            work.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), cur_w, cur_h, "png"
        work.save(buf, format="JPEG", quality=96, subsampling=0)
        return buf.getvalue(), cur_w, cur_h, "jpg"


def extract_public_profile_candidates(html_text: str, base_url: str = "") -> list[ProfileImageCandidate]:
    """
    Extract owner-scoped publicly exposed profile picture and cover photo URLs
    present in the returned page HTML (OpenGraph, JSON-LD, owner SSR fields, and header SVG).
    Avoids scraping unrelated avatars from comments or suggested profiles.
    """
    by_url: dict[str, ProfileImageCandidate] = {}

    def add_candidate(raw_val: Optional[str], label: str, is_cover: bool = False) -> None:
        if not raw_val or not isinstance(raw_val, str):
            return
        url = _unescape_embedded_url(raw_val)
        if base_url and not url.startswith(("http://", "https://")):
            url = urllib.parse.urljoin(base_url, url)
        if not url.startswith(("http://", "https://")) or is_generic_site_logo(url):
            return
        for idx, variant in enumerate(upgrade_public_avatar_url(url)):
            if variant not in by_url:
                variant_label = f"{label} (HD)" if (idx == 0 and variant != url and "HD" not in label) else label
                by_url[variant] = ProfileImageCandidate(
                    url=variant,
                    label=variant_label,
                    is_cover=is_cover,
                    ext=image_extension_from_url(variant).lstrip("."),
                )

    # 1. Explicit owner-scoped SSR profile avatar fields
    owner_avatar_patterns: list[tuple[re.Pattern[str], str, bool]] = [
        # Instagram / Threads
        (re.compile(r'"profile_pic_url_hd"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (HD)", False),
        (re.compile(r'"profile_pic_url"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        # Facebook owner profile avatar fields (flat and nested SSR objects)
        (re.compile(r'"profilePicLarge"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (Large)", False),
        (re.compile(r'"profilePic(?:Full|HD|High|Original|720|960|1080)[^"]*"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (HD)", False),
        (re.compile(r'"profile_picture(?:_for_sticky_bar|_url)?"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        (re.compile(r'"profilePicMedium"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (Medium)", False),
        (re.compile(r'"profilePic160"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (160px)", False),
        (re.compile(r'"profile_photo"\s*:\s*\{[^\r\n]{0,1200}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        (re.compile(r'"profilePhoto"\s*:\s*\{[^\r\n]{0,1200}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        (re.compile(r'"viewer_image"\s*:\s*\{[^\r\n]{0,250}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+\\?/(?:t39\.30808-1|t1\.6435-1)\\?/[^"]+)"', re.I), "Profile Picture (Full)", False),
        # Facebook profile header SVG avatar (allows nested <mask>/<g> inside <svg aria-label=...>)
        (re.compile(r'<svg[^>]+aria-label=[^>]*>(?:(?!</svg>).){0,2500}?<image[^>]+(?:xlink:)?href=["\'](https?://scontent[^"\']+)["\']', re.I | re.S), "Profile Picture (Header)", False),
        # TikTok
        (re.compile(r'"avatarLarger"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (Large)", False),
        (re.compile(r'"avatarMedium"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (Medium)", False),
        # X / Twitter
        (re.compile(r'"profile_image_url_https"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        # Cover / Banner photos (explicitly marked as cover so avatars always sort first)
        (re.compile(r'"cover_photo"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Photo", True),
        (re.compile(r'"coverPhoto"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Photo", True),
        (re.compile(r'"profile_banner_url"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Banner", True),
    ]
    for pattern, label, is_cover in owner_avatar_patterns:
        for match in pattern.finditer(html_text):
            add_candidate(match.group(1), label, is_cover=is_cover)

    # 2. JSON-LD structured public metadata (<script type="application/ld+json">)
    ld_pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )
    for match in ld_pattern.finditer(html_text):
        raw_json = match.group(1).strip()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
        except Exception:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for obj in items:
            if not isinstance(obj, dict):
                continue
            for key in ("image", "thumbnailUrl"):
                val = obj.get(key)
                if isinstance(val, str):
                    add_candidate(val, "Profile Picture (Structured)")
                elif isinstance(val, dict):
                    add_candidate(val.get("url") or val.get("contentUrl"), "Profile Picture (Structured)")
                elif isinstance(val, list):
                    for elem in val:
                        if isinstance(elem, str):
                            add_candidate(elem, "Profile Picture (Structured)")
                        elif isinstance(elem, dict):
                            add_candidate(elem.get("url") or elem.get("contentUrl"), "Profile Picture (Structured)")

    # 3. Standard OpenGraph / Twitter meta tags (authoritative public profile preview)
    meta_patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I), "Profile Picture (OpenGraph)"),
        (re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', re.I), "Profile Picture (OpenGraph)"),
        (re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I), "Profile Picture (Meta)"),
        (re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image', re.I), "Profile Picture (Meta)"),
        (re.compile(r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)', re.I), "Profile Picture (Link)"),
    ]
    for pattern, label in meta_patterns:
        for match in pattern.finditer(html_text):
            add_candidate(match.group(1), label)

    result = list(by_url.values())
    result.sort(
        key=lambda c: (0 if c.is_cover else 1, estimate_image_resolution_score(c.url)),
        reverse=True,
    )
    return result


def extract_facebook_photo_viewer_links(html_text: str) -> list[tuple[str, bool]]:
    """
    Extract standard Facebook photo viewer links (facebook.com/photo/?fbid=...) from a profile page
    for profile_photo and cover_photo so authorized sessions can fetch true native full-res photos.
    Returns list of (viewer_url, is_cover).
    """
    links: list[tuple[str, bool]] = []
    seen: set[str] = set()
    patterns = [
        (re.compile(r'"profile_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"(https?:\\?/\\?/[^"]*facebook\.com\\?/photo[^"]+)"', re.I), False),
        (re.compile(r'"profilePhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"(https?:\\?/\\?/[^"]*facebook\.com\\?/photo[^"]+)"', re.I), False),
        (re.compile(r'"cover_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"(https?:\\?/\\?/[^"]*facebook\.com\\?/photo[^"]+)"', re.I), True),
        (re.compile(r'"coverPhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"(https?:\\?/\\?/[^"]*facebook\.com\\?/photo[^"]+)"', re.I), True),
    ]
    for pattern, is_cover in patterns:
        for match in pattern.finditer(html_text):
            url = _unescape_embedded_url(match.group(1))
            if url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                links.append((url, is_cover))
    return links


def extract_photo_viewer_images(html_text: str, is_cover: bool = False) -> list[ProfileImageCandidate]:
    """
    Extract full-resolution image URLs from an authorized Facebook photo viewer page
    (facebook.com/photo/?fbid=...).
    """
    label = "Cover Photo (Native HD)" if is_cover else "Profile Picture (Native HD)"
    found: dict[str, ProfileImageCandidate] = {}

    patterns = [
        re.compile(r'"viewer_image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"currMedia"\s*:\s*\{[^\r\n]{0,600}?"image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"image"\s*:\s*\{[^\r\n]{0,200}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"[^\r\n]{0,120}?"height"\s*:\s*(\d{3,4})', re.I),
        re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://scontent[^"\']+)["\']', re.I),
    ]
    for pattern in patterns:
        for match in pattern.finditer(html_text):
            url = _unescape_embedded_url(match.group(1))
            if url.startswith(("http://", "https://")) and not is_generic_site_logo(url) and url not in found:
                found[url] = ProfileImageCandidate(
                    url=url,
                    label=label,
                    is_cover=is_cover,
                    ext=image_extension_from_url(url).lstrip("."),
                )

    result = list(found.values())
    result.sort(key=lambda c: estimate_image_resolution_score(c.url), reverse=True)
    return result


def extract_public_profile_images(html_text: str, base_url: str = "") -> list[str]:
    """Return owner-scoped publicly exposed profile image URLs ranked highest-resolution first."""
    return [c.url for c in extract_public_profile_candidates(html_text, base_url=base_url)]


def _read_image_bytes(
    image_url: str,
    timeout: int,
    cookie_jar: Optional[http.cookiejar.CookieJar] = None,
) -> tuple[bytes, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    try:
        from curl_cffi import requests as curl_requests

        cookie_dict = None
        if cookie_jar is not None:
            host = (urllib.parse.urlparse(image_url).hostname or "").lower()
            cookie_dict = {
                c.name: c.value
                for c in cookie_jar
                if c.value is not None
                and (not c.domain or host == c.domain.lstrip(".").lower() or host.endswith("." + c.domain.lstrip(".").lower()))
            } or None

        resp = curl_requests.get(
            image_url,
            headers=headers,
            cookies=cookie_dict,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )
        if 200 <= resp.status_code < 300:
            ct = (resp.headers.get("Content-Type") or "").lower()
            return resp.content, ct
    except Exception:
        pass

    request = urllib.request.Request(image_url, headers=headers, method="GET")
    opener = _build_url_opener(cookie_jar)
    with opener.open(request, timeout=timeout) as response:
        ct = (response.headers.get("Content-Type") or "").lower()
        return response.read(), ct


def probe_profile_image(
    candidate: ProfileImageCandidate,
    timeout: int,
    cookie_jar: Optional[http.cookiejar.CookieJar] = None,
) -> Optional[ProfileImageCandidate]:
    """
    Download and verify a candidate image, measuring real pixel dimensions (width x height),
    format extension, and exact byte size. Rejects non-images and tiny broken icons (< 64px).
    """
    try:
        data, content_type = _read_image_bytes(candidate.url, timeout=min(timeout, 12), cookie_jar=cookie_jar)
    except Exception:
        return None

    if len(data) < 512:
        return None
    if content_type and not (content_type.startswith("image/") or "octet-stream" in content_type):
        return None

    width: Optional[int] = None
    height: Optional[int] = None
    ext = candidate.ext or image_extension_from_url(candidate.url).lstrip(".")

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = (img.format or "").lower()
            if fmt == "jpeg":
                ext = "jpg"
            elif fmt in {"png", "webp", "gif", "avif"}:
                ext = fmt
    except Exception:
        # Reject data that Pillow cannot parse when Content-Type wasn't clearly an image
        if not content_type.startswith("image/"):
            return None

    # Filter out tiny UI icons / 1x1 tracking pixels / 48px thumbnails if broken
    if width is not None and height is not None and max(width, height) < 64:
        return None

    return ProfileImageCandidate(
        url=candidate.url,
        label=candidate.label,
        is_cover=candidate.is_cover,
        width=width,
        height=height,
        filesize=len(data),
        ext=ext or "jpg",
        verified=True,
    )


def inspect_profile_images(
    profile_url: str,
    platform: Platform,
    config: AppConfig,
    extractor: Optional[YTDLPExtractor] = None,
) -> list[ProfileImageCandidate]:
    """
    Discover, verify, and measure all publicly exposed (or cookie-authorized) images
    for a profile URL, sorted by Profile Pictures first and highest real pixel resolution first.
    """
    target = detect_target(profile_url, timeout=config.timeout)
    cookie_jar = load_cookie_jar(config)
    raw_candidates: list[ProfileImageCandidate] = []
    seen_urls: set[str] = set()

    def add_raw(item: ProfileImageCandidate) -> None:
        if item.url not in seen_urls and not is_generic_site_logo(item.url):
            seen_urls.add(item.url)
            raw_candidates.append(item)

    html_first_platforms = {
        Platform.FACEBOOK,
        Platform.INSTAGRAM,
        Platform.TWITTER,
        Platform.THREADS,
        Platform.BLUESKY,
        Platform.REDDIT,
    }

    def collect_from_html() -> None:
        try:
            page = fetch_public_html(target.normalized_url, config.timeout, cookie_jar=cookie_jar)
            for item in extract_public_profile_candidates(page, base_url=target.normalized_url):
                add_raw(item)

            # For Facebook profiles (especially with user cookies or unlocked profiles),
            # follow authorized photo viewer pages (facebook.com/photo/?fbid=...) for native full-res images.
            if platform == Platform.FACEBOOK:
                viewer_links = extract_facebook_photo_viewer_links(page)
                for viewer_url, is_cover in viewer_links[:3]:
                    try:
                        viewer_html = fetch_public_html(viewer_url, min(config.timeout, 15), cookie_jar=cookie_jar)
                        for v_item in extract_photo_viewer_images(viewer_html, is_cover=is_cover):
                            add_raw(v_item)
                    except Exception as v_exc:
                        LOGGER.debug("Photo viewer lookup skipped for %s: %s", viewer_url, v_exc)
        except ProfileError as exc:
            LOGGER.info("Profile HTML lookup failed: %s", exc)

    def collect_from_ytdlp() -> None:
        if extractor is None:
            return
        try:
            extracted = extractor.extract_info(
                target.normalized_url,
                download=False,
                extra={"skip_download": True, "extract_flat": True},
            )
            for url in extract_thumbnail_candidates(extracted):
                for variant in upgrade_public_avatar_url(url):
                    add_raw(
                        ProfileImageCandidate(
                            url=variant,
                            label="Profile Picture",
                            ext=image_extension_from_url(variant).lstrip("."),
                        )
                    )
        except ExtractionError as exc:
            LOGGER.info("yt-dlp profile metadata unavailable: %s", exc)

    if platform in html_first_platforms:
        collect_from_html()
        if not raw_candidates:
            collect_from_ytdlp()
    else:
        collect_from_ytdlp()
        collect_from_html()

    if not raw_candidates:
        return []

    to_probe = raw_candidates[:12]
    verified: list[ProfileImageCandidate] = []
    with ThreadPoolExecutor(max_workers=min(6, len(to_probe))) as pool:
        futures = [pool.submit(probe_profile_image, item, config.timeout, cookie_jar) for item in to_probe]
        for fut in futures:
            probed = fut.result()
            if probed is not None:
                verified.append(probed)

    # Sort verified images: non-cover Profile Pictures first, then highest real pixel area & filesize
    verified.sort(
        key=lambda c: (0 if c.is_cover else 1, c.pixel_area, c.filesize or 0),
        reverse=True,
    )

    # Deduplicate identical image renditions (same width, height, filesize)
    deduped: list[ProfileImageCandidate] = []
    seen_sig: set[tuple[bool, Optional[int], Optional[int], Optional[int]]] = set()
    for item in verified:
        sig = (item.is_cover, item.width, item.height, item.filesize)
        if sig not in seen_sig:
            seen_sig.add(sig)
            deduped.append(item)

    # If the highest-resolution owner profile picture is below HD (< 720px),
    # offer a detail-preserving HD Enhanced rendition at the top of Inspect Streams.
    best_avatar = next((c for c in deduped if not c.is_cover and c.width and c.height), None)
    if best_avatar is not None and best_avatar.width and best_avatar.height and max(best_avatar.width, best_avatar.height) < 720:
        hd_w, hd_h = compute_hd_target_dimensions(best_avatar.width, best_avatar.height)
        if hd_w > best_avatar.width or hd_h > best_avatar.height:
            deduped.insert(
                0,
                ProfileImageCandidate(
                    url=best_avatar.url,
                    label=f"Profile Picture (HD Enhanced from {best_avatar.width}x{best_avatar.height})",
                    is_cover=False,
                    width=hd_w,
                    height=hd_h,
                    filesize=None,
                    ext="png",
                    verified=True,
                    enhance_hd=True,
                ),
            )

    return deduped


def download_direct_profile_image(
    image_url: str,
    config: AppConfig,
    source_profile_url: Optional[str] = None,
    enhance_hd: bool = False,
) -> Path:
    """Download a specific discovered profile/cover image URL directly into output_dir/<platform>/profile_pictures/."""
    cookie_jar = load_cookie_jar(config)
    platform = Platform.UNKNOWN
    username = "profile_image"
    if source_profile_url:
        try:
            target = detect_target(source_profile_url, timeout=config.timeout)
            platform = target.platform
            username = extract_username_from_profile_url(target.normalized_url, platform) or "profile_image"
        except Exception:
            pass

    data, content_type = _read_image_bytes(image_url, timeout=config.timeout, cookie_jar=cookie_jar)
    if len(data) < 512 or (content_type and not (content_type.startswith("image/") or "octet-stream" in content_type)):
        raise ProfileError("The selected image URL did not return a valid image.")

    ext = image_extension_from_url(image_url)
    suffix_tag = ""
    if enhance_hd:
        try:
            data, hd_w, hd_h, hd_ext = enhance_image_bytes_to_hd(data)
            ext = f".{hd_ext}"
            suffix_tag = f"_HD_{hd_w}x{hd_h}"
        except Exception as exc:
            LOGGER.warning("HD image enhancement failed, saving original: %s", exc)
    else:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                fmt = (img.format or "").lower()
                if fmt == "jpeg":
                    ext = ".jpg"
                elif fmt in {"png", "webp", "gif", "avif"}:
                    ext = f".{fmt}"
        except Exception:
            pass

    destination_dir = config.output_dir / platform_directory(platform) / "profile_pictures"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = ensure_inside_directory(
        config.output_dir,
        unique_path(destination_dir / (sanitize_filename(username, "profile") + suffix_tag + ext)),
    )
    destination.write_bytes(data)
    return destination


def fetch_public_html(
    url: str,
    timeout: int,
    cookie_jar: Optional[http.cookiejar.CookieJar] = None,
) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "DPR": "3",
        "Sec-CH-DPR": "3",
        "Viewport-Width": "1920",
        "Sec-CH-Viewport-Width": "1920",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    # Prefer curl_cffi (Chrome HTTP/2 TLS fingerprint) when available so social platforms
    # return their normal public SSR HTML instead of an empty bot-check shell.
    try:
        from curl_cffi import requests as curl_requests

        cookie_dict = None
        if cookie_jar is not None:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            cookie_dict = {
                c.name: c.value
                for c in cookie_jar
                if c.value is not None
                and (not c.domain or host == c.domain.lstrip(".").lower() or host.endswith("." + c.domain.lstrip(".").lower()))
            } or None

        resp = curl_requests.get(
            url,
            headers=headers,
            cookies=cookie_dict,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )
        if 200 <= resp.status_code < 400 and resp.text:
            return resp.text
    except Exception as exc:
        LOGGER.debug("curl_cffi profile HTML fetch fallback to urllib: %s", exc)

    request = urllib.request.Request(url, headers=headers, method="GET")
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
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not (
                content_type.startswith("image/") or "octet-stream" in content_type
            ):
                raise ProfileError(f"Expected image response, got {content_type}.")
            with temp_path.open("wb") as fh:
                shutil.copyfileobj(response, fh, length=1024 * 128)

        if temp_path.stat().st_size < 512:
            raise ProfileError("Downloaded profile image was empty or invalid.")

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
            info("Resolving verified profile images using your configured session cookies...", self.config)
        else:
            info("Resolving verified publicly exposed profile images...", self.config)

        verified = inspect_profile_images(
            target.normalized_url,
            platform=platform,
            config=self.config,
            extractor=self.extractor,
        )

        if not verified:
            if cookie_jar is not None:
                raise ProfileError(
                    "No valid profile picture could be resolved with your current session cookies. "
                    "The account may be private/locked to accounts without permission, or cookies may need refreshing."
                )
            raise ProfileError(
                "No valid publicly exposed profile image could be resolved. "
                "If your account is authorized to view this profile, select Browser Cookies or import cookies.txt and try again."
            )

        username = (
            username_hint
            or extract_username_from_profile_url(target.normalized_url, platform)
            or "profile"
        )

        best = verified[0]
        if best.enhance_hd:
            info(
                f"Source profile picture is below HD; enhancing cleanly to {best.width}x{best.height} HD...",
                self.config,
            )
            return download_direct_profile_image(
                best.url,
                self.config,
                source_profile_url=target.normalized_url,
                enhance_hd=True,
            )

        filename = sanitize_filename(username, "profile") + "." + (best.ext.lstrip(".") or "jpg")
        destination_dir = (
            self.config.output_dir
            / platform_directory(platform)
            / "profile_pictures"
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = ensure_inside_directory(self.config.output_dir, destination_dir / filename)

        for item in verified:
            try:
                return download_public_image(
                    item.url,
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
