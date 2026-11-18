"""Public and cookie-authorized profile photo resolution and image extraction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
from universal_downloader.paths import get_default_download_dir
from universal_downloader.upscaler import (
    compute_hd_target_dimensions,
    enhance_image_bytes_to_hd,
    find_local_onnx_upscaler,
)
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


def _load_netscape_cookie_jar(path: Path) -> http.cookiejar.CookieJar:
    """
    Parse a Netscape cookies.txt file into a CookieJar, properly supporting #HttpOnly_ lines
    (which Python's stdlib MozillaCookieJar silently skips, dropping Facebook's xs/datr/sb session cookies).
    """
    jar = http.cookiejar.CookieJar()
    raw_text = path.read_text(encoding="utf-8-sig", errors="replace")
    loaded = 0

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.lower().startswith("#httponly_"):
                line = line[len("#HttpOnly_"):]
            else:
                continue

        cols = line.split("\t")
        if len(cols) < 7:
            continue

        domain, flag, cookie_path, secure_str, expires_str, name, value = (
            cols[0].strip(),
            cols[1].strip().upper(),
            cols[2].strip() or "/",
            cols[3].strip().upper(),
            cols[4].strip(),
            cols[5].strip(),
            cols[6].strip(),
        )
        if not domain or not name:
            continue

        try:
            expires_val: Optional[int] = int(expires_str)
            if expires_val <= 0:
                expires_val = None
        except ValueError:
            expires_val = None

        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith(".") or flag == "TRUE",
            path=cookie_path,
            path_specified=True,
            secure=(secure_str == "TRUE"),
            expires=expires_val,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        jar.set_cookie(cookie)
        loaded += 1

    LOGGER.debug("Loaded %d cookie(s) from %s", loaded, path)
    return jar


def load_cookie_jar(config: AppConfig) -> Optional[http.cookiejar.CookieJar]:
    """Load the user's configured cookies (cookies.txt or browser session) for authorized profile access."""
    if config.cookies_file and config.cookies_file.exists():
        try:
            jar = _load_netscape_cookie_jar(config.cookies_file)
            if len(jar) > 0:
                return jar
        except Exception as exc:
            LOGGER.warning("Could not load cookies file %s: %s", config.cookies_file, exc)

    if config.cookies_from_browser:
        try:
            from yt_dlp.cookies import extract_cookies_from_browser

            return extract_cookies_from_browser(config.cookies_from_browser)
        except Exception as exc:
            err_text = str(exc)
            lowered = err_text.lower()
            if "could not copy" in lowered or "cookie database" in lowered or "dpapi" in lowered or "app-bound" in lowered:
                LOGGER.warning(
                    "Browser '%s' locks or encrypts its cookie database while running on Windows. "
                    "Use the 'Paste Cookies' button (or import cookies.txt), switch to Firefox, or close '%s' completely and retry.",
                    config.cookies_from_browser,
                    config.cookies_from_browser,
                )
            else:
                LOGGER.warning("Could not load cookies from browser '%s': %s", config.cookies_from_browser, err_text)

    return None


def _build_cookie_header(
    cookie_jar: Optional[http.cookiejar.CookieJar],
    url: str,
) -> Optional[str]:
    """Build a verbatim RFC Cookie header string for cookies matching the target host."""
    if cookie_jar is None:
        return None
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host:
        return None
    pairs: dict[str, str] = {}
    for c in cookie_jar:
        if c.value is None:
            continue
        domain = (c.domain or "").lstrip(".").lower()
        if not domain or host == domain or host.endswith("." + domain):
            pairs[c.name] = c.value
    if not pairs:
        return None
    return "; ".join(f"{name}={val}" for name, val in pairs.items())


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

    # X / Twitter: replace _normal (48x48), _bigger (73x73), _200x200, or _400x400 with original full size
    if "pbs.twimg.com/profile_images/" in lowered:
        for suffix in ("_normal.", "_bigger.", "_mini.", "_200x200.", "_400x400."):
            if suffix in url:
                variants.append(url.replace(suffix, "."))
                if suffix != "_400x400.":
                    variants.append(url.replace(suffix, "_400x400."))
                break

    # YouTube / Google CDN: upgrade =s88 / =s176 / =s240 / =s480 avatars to =s1024 and =s2048
    if ("yt3.googleusercontent.com" in lowered or "yt3.ggpht.com" in lowered) and re.search(r"=s\d{2,3}(?=[-&]|$)", url):
        variants.append(re.sub(r"=s\d{2,3}(?=[-&]|$)", "=s2048", url))
        variants.append(re.sub(r"=s\d{2,3}(?=[-&]|$)", "=s1024", url))

    # X / Twitter banners: prefer /1500x500 full banner rendition
    if "pbs.twimg.com/profile_banners/" in lowered and not re.search(r"/\d{3,4}x\d{3,4}$", url):
        variants.append(url.rstrip("/") + "/1500x500")

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


@dataclass
class ProfileInfoField:
    """A single public metadata chip shown on the profile preview card (click-to-copy)."""
    label: str
    value: str
    copy_value: Optional[str] = None

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "value": self.value,
            "copy_value": self.copy_value if self.copy_value is not None else self.value,
        }


@dataclass
class ProfileInspectionResult:
    """Structured result of profile picture inspection including platform lock notices, ID, and public metadata."""
    images: list[ProfileImageCandidate]
    profile_locked: bool = False
    profile_notice: Optional[str] = None
    title: Optional[str] = None
    profile_id: Optional[str] = None
    bio: Optional[str] = None
    is_verified: bool = False
    profile_info: list[ProfileInfoField] = field(default_factory=list)


def _format_compact_count(raw: Any) -> Optional[str]:
    """Format an integer or numeric string (e.g. 12450 -> '12.5K', 1500000 -> '1.5M')."""
    if raw is None:
        return None
    if isinstance(raw, str):
        cleaned = raw.strip().replace(",", "")
        if not cleaned:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?[KMBkmb]", cleaned):
            return cleaned.upper()
        try:
            num = int(float(cleaned))
        except ValueError:
            return raw.strip()
    else:
        try:
            num = int(raw)
        except (TypeError, ValueError):
            return None

    if num < 0:
        return None
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B".replace(".0B", "B")
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".replace(".0M", "M")
    if num >= 1_000:
        return f"{num / 1_000:.1f}K".replace(".0K", "K")
    return str(num)


def _unescape_json_text(raw: str) -> str:
    """Decode JSON-escaped unicode/newlines safely into clean display text."""
    try:
        decoded = json.loads(f'"{raw}"')
        if isinstance(decoded, str):
            return re.sub(r"\s+", " ", html.unescape(decoded)).strip()
    except Exception:
        pass
    cleaned = raw.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ").replace("\\/", "/")
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()


def _extract_meta_description(html_text: str) -> Optional[str]:
    for pattern in (
        re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', re.I),
        re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', re.I),
        re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', re.I),
        re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', re.I),
    ):
        match = pattern.search(html_text)
        if match:
            val = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
            if val:
                return val
    return None


def extract_facebook_user_id(profile_url: str, html_text: str = "") -> Optional[str]:
    """
    Extract the target Facebook profile/page numeric ID from a profile URL or standard page HTML.
    Uses owner-scoped fields (and case-sensitive 'userID') to avoid confusing with the logged-in viewer's 'USER_ID'.
    """
    if profile_url:
        parsed = urllib.parse.urlparse(profile_url)
        if parsed.path.rstrip("/").lower().endswith("/profile.php"):
            qs = urllib.parse.parse_qs(parsed.query)
            raw_id = (qs.get("id") or [None])[0]
            if raw_id and raw_id.isdigit() and len(raw_id) >= 5:
                return raw_id

    if not html_text:
        return None

    # Order from most specific profile-owner fields to general page metadata
    patterns = (
        re.compile(r'fb://(?:profile|page)/(\d{5,})', re.I),
        re.compile(r'"profile_owner"\s*:\s*\{[^\r\n]{0,160}?"id"\s*:\s*"(\d{5,})"'),
        re.compile(r'"userID"\s*:\s*"(\d{5,})"'),
        re.compile(r'"profile_header_renderer"\s*:\s*\{[^\r\n]{0,400}?"id"\s*:\s*"(\d{5,})"'),
        re.compile(r'"entity_id"\s*:\s*"(\d{5,})"'),
        re.compile(r'"delegate_page_id"\s*:\s*"(\d{5,})"'),
    )
    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            return match.group(1)

    return None


def extract_profile_metadata_fields(
    platform: Platform,
    profile_url: str,
    html_text: str = "",
    extra_data: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str], bool, bool, list[ProfileInfoField]]:
    """
    Extract public, click-to-copy profile metadata fields across all supported social platforms
    (User/Channel ID, @handle, followers/following/posts/likes/karma, category, bio, verified/private flags).
    Returns (profile_id, bio, is_verified, is_private_or_locked, info_fields).
    """
    fields: list[ProfileInfoField] = []
    seen_labels: set[str] = set()
    profile_id: Optional[str] = None
    bio: Optional[str] = None
    is_verified = False
    is_private = False

    def add_field(label: str, value: Optional[str], copy_value: Optional[str] = None) -> None:
        if not value or not value.strip() or label in seen_labels:
            return
        seen_labels.add(label)
        fields.append(ProfileInfoField(label=label, value=value.strip(), copy_value=(copy_value or value).strip()))

    def add_count(label: str, raw_val: Any) -> None:
        if raw_val is None:
            return
        formatted = _format_compact_count(raw_val)
        if not formatted:
            return
        raw_copy = str(raw_val).strip()
        add_field(label, formatted, copy_value=raw_copy if raw_copy.isdigit() else formatted)

    username = extract_username_from_profile_url(profile_url, platform)
    meta_desc = _extract_meta_description(html_text) if html_text else None

    if platform == Platform.FACEBOOK:
        profile_id = extract_facebook_user_id(profile_url, html_text)
        if profile_id:
            add_field("ID", profile_id)
        if username and username != profile_id and username != "facebook_profile":
            add_field("Username", f"@{username}", copy_value=username)

        if html_text:
            is_private = detect_facebook_profile_locked(html_text)
            if re.search(r'"is_verified"\s*:\s*true', html_text):
                is_verified = True
            cat_m = re.search(r'"category_name"\s*:\s*"([^"]{2,60})"', html_text)
            if cat_m:
                add_field("Category", _unescape_json_text(cat_m.group(1)))

            fol_m = re.search(r'"follower_count"\s*:\s*(\d+)', html_text)
            if fol_m:
                add_count("Followers", fol_m.group(1))
            elif meta_desc:
                m_likes = re.search(r'([\d.,]+[KMBkmb]?)\s+likes?', meta_desc, re.I)
                m_fols = re.search(r'([\d.,]+[KMBkmb]?)\s+followers?', meta_desc, re.I)
                if m_fols:
                    add_count("Followers", m_fols.group(1))
                elif m_likes:
                    add_count("Likes", m_likes.group(1))

            if meta_desc and "join facebook to connect" not in meta_desc.lower() and "is on facebook" not in meta_desc.lower():
                bio = meta_desc[:220]

    elif platform == Platform.INSTAGRAM:
        if html_text:
            for pat in (
                re.compile(r'"profilePage_(\d{5,})"'),
                re.compile(r'"target_id"\s*:\s*"(\d{5,})"'),
                re.compile(r'"props"\s*:\s*\{[^\r\n]{0,400}?"id"\s*:\s*"(\d{5,})"'),
                re.compile(r'"user_id"\s*:\s*"(\d{5,})"'),
            ):
                m = pat.search(html_text)
                if m:
                    profile_id = m.group(1)
                    break
            if re.search(r'"is_verified"\s*:\s*true', html_text):
                is_verified = True
            if re.search(r'"is_private"\s*:\s*true', html_text):
                is_private = True

        if profile_id:
            add_field("ID", profile_id)
        if username:
            add_field("Username", f"@{username}", copy_value=username)

        if html_text:
            fol_m = re.search(r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html_text) or re.search(r'"follower_count"\s*:\s*(\d+)', html_text)
            fng_m = re.search(r'"edge_follow"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html_text) or re.search(r'"following_count"\s*:\s*(\d+)', html_text)
            pst_m = re.search(r'"edge_owner_to_timeline_media"\s*:\s*\{\s*"count"\s*:\s*(\d+)', html_text) or re.search(r'"media_count"\s*:\s*(\d+)', html_text)
            if fol_m:
                add_count("Followers", fol_m.group(1))
            if fng_m:
                add_count("Following", fng_m.group(1))
            if pst_m:
                add_count("Posts", pst_m.group(1))
            bio_m = re.search(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text)
            if bio_m and bio_m.group(1):
                bio = _unescape_json_text(bio_m.group(1))[:220]

        if meta_desc:
            if "Followers" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Followers', meta_desc, re.I)
                if m:
                    add_count("Followers", m.group(1))
            if "Following" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Following', meta_desc, re.I)
                if m:
                    add_count("Following", m.group(1))
            if "Posts" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Posts', meta_desc, re.I)
                if m:
                    add_count("Posts", m.group(1))

    elif platform == Platform.TIKTOK:
        if html_text:
            uid_m = re.search(r'"userInfo"\s*:\s*\{\s*"user"\s*:\s*\{[^\r\n]{0,400}?"id"\s*:\s*"(\d{5,})"', html_text)
            if not uid_m:
                uid_m = re.search(r'"uniqueId"\s*:\s*"[^"]+"[^\r\n]{0,200}?"id"\s*:\s*"(\d{5,})"', html_text)
            if uid_m:
                profile_id = uid_m.group(1)

            if re.search(r'"user"\s*:\s*\{[^\r\n]{0,400}?"verified"\s*:\s*true', html_text):
                is_verified = True
            if re.search(r'"privateAccount"\s*:\s*true', html_text):
                is_private = True

        if profile_id:
            add_field("ID", profile_id)
        if username:
            add_field("Username", f"@{username}", copy_value=username)

        if html_text:
            for key, label in (
                ("followerCount", "Followers"),
                ("followingCount", "Following"),
                ("heartCount", "Likes"),
                ("videoCount", "Videos"),
            ):
                m = re.search(rf'"{key}"\s*:\s*(\d+)', html_text)
                if m:
                    add_count(label, m.group(1))
            sig_m = re.search(r'"signature"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text)
            if sig_m and sig_m.group(1):
                bio = _unescape_json_text(sig_m.group(1))[:220]

        if meta_desc:
            if "Followers" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Followers', meta_desc, re.I)
                if m:
                    add_count("Followers", m.group(1))
            if "Likes" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Likes', meta_desc, re.I)
                if m:
                    add_count("Likes", m.group(1))

    elif platform == Platform.TWITTER:
        if html_text:
            id_m = re.search(r'"rest_id"\s*:\s*"(\d{5,})"', html_text) or re.search(r'"identifier"\s*:\s*"(\d{5,})"', html_text)
            if id_m:
                profile_id = id_m.group(1)
            if re.search(r'"(?:is_blue_verified|verified)"\s*:\s*true', html_text):
                is_verified = True
            if re.search(r'"protected"\s*:\s*true', html_text):
                is_private = True

        if profile_id:
            add_field("ID", profile_id)
        if username:
            add_field("Username", f"@{username}", copy_value=username)

        if html_text:
            for key, label in (
                ("followers_count", "Followers"),
                ("friends_count", "Following"),
                ("statuses_count", "Posts"),
            ):
                m = re.search(rf'"{key}"\s*:\s*(\d+)', html_text)
                if m:
                    add_count(label, m.group(1))
            bio_m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text)
            if bio_m and bio_m.group(1):
                bio = _unescape_json_text(bio_m.group(1))[:220]

    elif platform == Platform.YOUTUBE:
        parsed = urllib.parse.urlparse(profile_url)
        ch_m = re.search(r'/channel/(UC[A-Za-z0-9_-]{20,})', parsed.path)
        if ch_m:
            profile_id = ch_m.group(1)
        elif html_text:
            for pat in (
                re.compile(r'<meta[^>]+itemprop=["\']identifier["\'][^>]+content=["\'](UC[A-Za-z0-9_-]{20,})["\']', re.I),
                re.compile(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{20,})"'),
                re.compile(r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{20,})"'),
            ):
                m = pat.search(html_text)
                if m:
                    profile_id = m.group(1)
                    break

        if profile_id:
            add_field("Channel ID", profile_id)
        if username and not username.startswith("UC"):
            add_field("Handle", f"@{username}", copy_value=f"@{username}")

        if html_text:
            sub_m = re.search(r'"subscriberCountText"\s*:\s*\{[^\r\n]{0,120}?"simpleText"\s*:\s*"([^"]+)"', html_text)
            if sub_m:
                sub_val = re.sub(r'\s*subscribers?$', '', sub_m.group(1), flags=re.I).strip()
                add_field("Subscribers", sub_val)
            vid_m = re.search(r'"videosCountText"\s*:\s*\{[^\r\n]{0,120}?"text"\s*:\s*"([\d.,]+[KMBkmb]?)"', html_text)
            if vid_m:
                add_count("Videos", vid_m.group(1))
            if meta_desc:
                bio = meta_desc[:220]

    elif platform == Platform.THREADS:
        if html_text:
            id_m = re.search(r'"user_id"\s*:\s*"(\d{5,})"', html_text) or re.search(r'"pk"\s*:\s*"(\d{5,})"', html_text)
            if id_m:
                profile_id = id_m.group(1)
            if re.search(r'"is_verified"\s*:\s*true', html_text):
                is_verified = True
            if re.search(r'"is_private"\s*:\s*true', html_text):
                is_private = True

        if profile_id:
            add_field("ID", profile_id)
        if username:
            add_field("Username", f"@{username}", copy_value=username)

        if html_text:
            fol_m = re.search(r'"follower_count"\s*:\s*(\d+)', html_text)
            if fol_m:
                add_count("Followers", fol_m.group(1))
        if meta_desc:
            if "Followers" not in seen_labels:
                m = re.search(r'([\d.,]+[KMBkmb]?)\s+Followers', meta_desc, re.I)
                if m:
                    add_count("Followers", m.group(1))
            bio = meta_desc[:220]

    elif platform == Platform.REDDIT:
        if html_text:
            id_m = re.search(r'"id"\s*:\s*"(t2_[a-z0-9]+)"', html_text, re.I)
            if id_m:
                profile_id = id_m.group(1)
        if profile_id:
            add_field("ID", profile_id)
        if username:
            add_field("Username", f"u/{username}", copy_value=f"u/{username}")
        if html_text:
            karma_m = re.search(r'"total_karma"\s*:\s*(\d+)', html_text)
            if karma_m:
                add_count("Karma", karma_m.group(1))

    elif platform == Platform.BLUESKY:
        if isinstance(extra_data, dict):
            did = extra_data.get("did")
            handle = extra_data.get("handle")
            if isinstance(did, str) and did:
                profile_id = did
                add_field("DID", did)
            if isinstance(handle, str) and handle:
                add_field("Handle", f"@{handle}", copy_value=handle)
            add_count("Followers", extra_data.get("followersCount"))
            add_count("Following", extra_data.get("followsCount"))
            add_count("Posts", extra_data.get("postsCount"))
            desc = extra_data.get("description")
            if isinstance(desc, str) and desc.strip():
                bio = re.sub(r"\s+", " ", desc).strip()[:220]
        elif username:
            add_field("Handle", f"@{username}", copy_value=username)

    else:
        if username:
            add_field("Username", f"@{username}", copy_value=username)

    return profile_id, bio, is_verified, is_private, fields


def detect_facebook_profile_locked(html_text: str) -> bool:
    """Detect when Facebook's standard web HTML explicitly indicates Profile Lock is active."""
    if not html_text:
        return False
    lock_patterns = (
        re.compile(r'"is_profile_locked"\s*:\s*true', re.I),
        re.compile(r'"locked_profile_status"\s*:\s*"LOCKED"', re.I),
        re.compile(r'"profile_lock_status"\s*:\s*"[^"]*LOCKED', re.I),
        re.compile(r'\blocked\s+(?:his|her|their|your)\s+profile\b', re.I),
    )
    return any(p.search(html_text) for p in lock_patterns)


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

    # 1. Explicit owner-scoped SSR profile avatar fields across platforms
    owner_avatar_patterns: list[tuple[re.Pattern[str], str, bool]] = [
        # Instagram / Threads (both public and cookie-authorized HD renditions)
        (re.compile(r'"hd_profile_pic_url_info"\s*:\s*\{[^\r\n]{0,250}?"url"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (Native HD)", False),
        (re.compile(r'"hd_profile_pic_versions"\s*:\s*\[[^\r\n]{0,800}?"url"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (HD)", False),
        (re.compile(r'"profile_pic_url_hd"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture (HD)", False),
        (re.compile(r'"profile_pic_url"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        # Facebook owner profile avatar fields (strictly owner-scoped so logged-in sidebar/chat avatars are never picked)
        (re.compile(r'"profilePic(?:Large|Medium|Small|\d+)"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        (re.compile(r'"profile_picture_for_sticky_bar"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
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
        # Reddit
        (re.compile(r'"(?:icon_img|snoovatar_img)"\s*:\s*"(https?:[^"]+)"', re.I), "Profile Picture", False),
        # Cover / Banner photos (explicitly marked as cover so avatars always sort first)
        (re.compile(r'"cover_photo"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Photo", True),
        (re.compile(r'"coverPhoto"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Photo", True),
        (re.compile(r'"profile_banner_url"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Banner", True),
        (re.compile(r'"banner_img"\s*:\s*"(https?:[^"]+)"', re.I), "Cover Banner", True),
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

    def add_link(raw_url: str, is_cover: bool) -> None:
        url = _unescape_embedded_url(raw_url)
        if url.startswith("/"):
            url = f"https://www.facebook.com{url}"
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            links.append((url, is_cover))

    url_patterns = [
        (re.compile(r'"profile_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo(?:\.php)?[^"]+)"', re.I), False),
        (re.compile(r'"profilePhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo(?:\.php)?[^"]+)"', re.I), False),
        (re.compile(r'"cover_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo(?:\.php)?[^"]+)"', re.I), True),
        (re.compile(r'"coverPhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo(?:\.php)?[^"]+)"', re.I), True),
    ]
    for pattern, is_cover in url_patterns:
        for match in pattern.finditer(html_text):
            add_link(match.group(1), is_cover)

    # Also resolve photo IDs inside profile_photo / cover_photo objects when URL isn't inlined
    id_patterns = [
        (re.compile(r'"profile_photo"\s*:\s*\{[^\r\n]{0,300}?"id"\s*:\s*"(\d{6,})"', re.I), False),
        (re.compile(r'"cover_photo"\s*:\s*\{[^\r\n]{0,300}?"id"\s*:\s*"(\d{6,})"', re.I), True),
    ]
    for pattern, is_cover in id_patterns:
        for match in pattern.finditer(html_text):
            fbid = match.group(1)
            if not any(f"fbid={fbid}" in existing for existing, _ in links):
                add_link(f"https://www.facebook.com/photo/?fbid={fbid}", is_cover)

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
        re.compile(r'"full_width_image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"currMedia"\s*:\s*\{[^\r\n]{0,600}?"image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"photo_image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"image"\s*:\s*\{[^\r\n]{0,200}?"height"\s*:\s*\d{3,4}[^\r\n]{0,200}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"', re.I),
        re.compile(r'"image"\s*:\s*\{[^\r\n]{0,200}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"[^\r\n]{0,200}?"height"\s*:\s*\d{3,4}', re.I),
        re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://scontent[^"\']+)["\']', re.I),
        re.compile(r'<meta[^>]+content=["\'](https?://scontent[^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
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

        req_headers = dict(headers)
        cookie_header = _build_cookie_header(cookie_jar, image_url)
        if cookie_header:
            req_headers["Cookie"] = cookie_header

        resp = curl_requests.get(
            image_url,
            headers=req_headers,
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


def _fetch_bluesky_public_profile(
    profile_url: str,
    timeout: int,
) -> tuple[list[ProfileImageCandidate], Optional[str], Optional[dict[str, Any]]]:
    """Query Bluesky's official public AppView API for full-resolution avatar, banner, and profile stats."""
    actor = extract_username_from_profile_url(profile_url, Platform.BLUESKY)
    if not actor:
        return [], None, None
    api_url = f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={urllib.parse.quote(actor)}"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"Accept": "application/json", "User-Agent": "UniversalMediaDownloader/2.6"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=min(timeout, 12)) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return [], None, None

    found: list[ProfileImageCandidate] = []
    if isinstance(data, dict):
        avatar = data.get("avatar")
        banner = data.get("banner")
        display_name = data.get("displayName") or data.get("handle")
        if isinstance(avatar, str) and avatar.startswith(("http://", "https://")):
            found.append(
                ProfileImageCandidate(
                    url=avatar,
                    label="Profile Picture (Native HD)",
                    is_cover=False,
                    ext=image_extension_from_url(avatar).lstrip("."),
                )
            )
        if isinstance(banner, str) and banner.startswith(("http://", "https://")):
            found.append(
                ProfileImageCandidate(
                    url=banner,
                    label="Cover Banner (Native HD)",
                    is_cover=True,
                    ext=image_extension_from_url(banner).lstrip("."),
                )
            )
        return found, (display_name if isinstance(display_name, str) else None), data
    return [], None, None


def inspect_profile_images_detailed(
    profile_url: str,
    platform: Platform,
    config: AppConfig,
    extractor: Optional[YTDLPExtractor] = None,
) -> ProfileInspectionResult:
    """
    Discover, verify, and measure all publicly exposed (or cookie-authorized) images
    for a profile URL, returning verified images plus platform lock status, ID, bio, and metadata fields.
    """
    target = detect_target(profile_url, timeout=config.timeout)
    cookie_jar = load_cookie_jar(config)
    raw_candidates: list[ProfileImageCandidate] = []
    seen_urls: set[str] = set()
    profile_locked = False
    resolved_title: Optional[str] = None
    resolved_profile_id, resolved_bio, resolved_verified, _, resolved_info = extract_profile_metadata_fields(
        platform, target.normalized_url
    )
    had_profile_viewer_hd = False

    def add_raw(item: ProfileImageCandidate) -> None:
        if item.url not in seen_urls and not is_generic_site_logo(item.url):
            seen_urls.add(item.url)
            raw_candidates.append(item)

    html_first_platforms = {
        Platform.FACEBOOK,
        Platform.INSTAGRAM,
        Platform.TIKTOK,
        Platform.TWITTER,
        Platform.THREADS,
        Platform.BLUESKY,
        Platform.REDDIT,
        Platform.YOUTUBE,
    }

    def collect_from_html() -> None:
        nonlocal profile_locked, resolved_title, resolved_profile_id, resolved_bio, resolved_verified, resolved_info, had_profile_viewer_hd

        bsky_data: Optional[dict[str, Any]] = None
        if platform == Platform.BLUESKY:
            bsky_imgs, bsky_title, bsky_data = _fetch_bluesky_public_profile(target.normalized_url, config.timeout)
            if bsky_title:
                resolved_title = bsky_title
            for item in bsky_imgs:
                add_raw(item)
            if bsky_data:
                pid, bio, ver, priv, info_fields = extract_profile_metadata_fields(
                    platform, target.normalized_url, extra_data=bsky_data
                )
                resolved_profile_id = pid or resolved_profile_id
                resolved_bio = bio or resolved_bio
                resolved_verified = resolved_verified or ver
                profile_locked = profile_locked or priv
                if info_fields:
                    resolved_info = info_fields

        try:
            page = fetch_public_html(target.normalized_url, config.timeout, cookie_jar=cookie_jar)
            if not resolved_title:
                resolved_title = extract_profile_title(page)

            pid, bio, ver, priv, info_fields = extract_profile_metadata_fields(
                platform, target.normalized_url, page, extra_data=bsky_data
            )
            if pid:
                resolved_profile_id = pid
            if bio:
                resolved_bio = bio
            if ver:
                resolved_verified = True
            if priv:
                profile_locked = True
            if info_fields and (not bsky_data or len(info_fields) > len(resolved_info)):
                resolved_info = info_fields

            for item in extract_public_profile_candidates(page, base_url=target.normalized_url):
                add_raw(item)

            # For Facebook profiles (especially with user cookies or unlocked profiles),
            # follow authorized photo viewer pages (facebook.com/photo/?fbid=...) for native full-res images.
            if platform == Platform.FACEBOOK:
                viewer_links = extract_facebook_photo_viewer_links(page)
                for viewer_url, is_cover in viewer_links[:4]:
                    try:
                        viewer_html = fetch_public_html(viewer_url, min(config.timeout, 15), cookie_jar=cookie_jar)
                        for v_item in extract_photo_viewer_images(viewer_html, is_cover=is_cover):
                            if not is_cover:
                                had_profile_viewer_hd = True
                            add_raw(v_item)
                    except Exception as v_exc:
                        LOGGER.debug("Photo viewer lookup skipped for %s: %s", viewer_url, v_exc)
        except ProfileError as exc:
            LOGGER.info("Profile HTML lookup failed: %s", exc)

    def collect_from_ytdlp() -> None:
        nonlocal resolved_title
        if extractor is None:
            return
        try:
            extracted = extractor.extract_info(
                target.normalized_url,
                download=False,
                extra={"skip_download": True, "extract_flat": True},
            )
            if not resolved_title and isinstance(extracted, dict):
                t = extracted.get("uploader") or extracted.get("channel") or extracted.get("title")
                if isinstance(t, str) and t.strip():
                    resolved_title = t.strip()
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
        notice = (
            "Profile is locked by the platform; no high-resolution images are publicly accessible."
            if profile_locked
            else None
        )
        return ProfileInspectionResult(
            images=[],
            profile_locked=profile_locked,
            profile_notice=notice,
            title=resolved_title,
            profile_id=resolved_profile_id,
            bio=resolved_bio,
            is_verified=resolved_verified,
            profile_info=resolved_info,
        )

    # Prioritize authorized Native HD viewer candidates and highest estimated resolution before probing
    raw_candidates.sort(
        key=lambda c: (
            1 if "Native HD" in c.label else 0,
            0 if c.is_cover else 1,
            estimate_image_resolution_score(c.url),
        ),
        reverse=True,
    )

    to_probe = raw_candidates[:16]
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
    onnx_available = find_local_onnx_upscaler() is not None
    if best_avatar is not None and best_avatar.width and best_avatar.height and max(best_avatar.width, best_avatar.height) < 720:
        hd_w, hd_h = compute_hd_target_dimensions(best_avatar.width, best_avatar.height)
        if hd_w > best_avatar.width or hd_h > best_avatar.height:
            engine_tag = "AI Super-Res" if onnx_available else "HD Enhanced"
            deduped.insert(
                0,
                ProfileImageCandidate(
                    url=best_avatar.url,
                    label=f"Profile Picture ({engine_tag} from {best_avatar.width}x{best_avatar.height})",
                    is_cover=False,
                    width=hd_w,
                    height=hd_h,
                    filesize=None,
                    ext="png",
                    verified=True,
                    enhance_hd=True,
                ),
            )

    profile_notice: Optional[str] = None
    is_restricted = profile_locked and not had_profile_viewer_hd
    if is_restricted:
        if platform == Platform.FACEBOOK:
            profile_notice = (
                "Profile Locked by Facebook — Only small identification avatars are exposed to non-friends. "
                "Use the HD Enhanced rendition above for the sharpest available output."
            )
            LOGGER.info("Profile lock detected on %s; platform restricts non-friend avatar resolution.", target.normalized_url)
        else:
            profile_notice = (
                f"Private account on {platform.value.capitalize()} — Only publicly exposed profile preview metadata and avatar are available."
            )

    return ProfileInspectionResult(
        images=deduped,
        profile_locked=is_restricted,
        profile_notice=profile_notice,
        title=resolved_title,
        profile_id=resolved_profile_id,
        bio=resolved_bio,
        is_verified=resolved_verified,
        profile_info=resolved_info,
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
    return inspect_profile_images_detailed(
        profile_url,
        platform=platform,
        config=config,
        extractor=extractor,
    ).images


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

    try:
        destination_dir = config.output_dir / platform_directory(platform) / "profile_pictures"
        destination_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        config.output_dir = get_default_download_dir()
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
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    cookie_header = _build_cookie_header(cookie_jar, url)
    if cookie_header:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        LOGGER.info("Using %d session cookie(s) for %s", cookie_header.count(";") + 1, host)

    # Prefer curl_cffi (Chrome HTTP/2 TLS fingerprint) when available so social platforms
    # return their normal public SSR HTML instead of an empty bot-check shell.
    try:
        from curl_cffi import requests as curl_requests

        req_headers = dict(headers)
        if cookie_header:
            req_headers["Cookie"] = cookie_header

        resp = curl_requests.get(
            url,
            headers=req_headers,
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

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        fallback_root = get_default_download_dir()
        destination = fallback_root / destination.name
        base_dir = fallback_root
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
        try:
            destination_dir = (
                self.config.output_dir
                / platform_directory(platform)
                / "profile_pictures"
            )
            destination_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            self.config.output_dir = get_default_download_dir()
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
