#!/usr/bin/env python3
"""
Universal Media Downloader
Version 1.0.0

A single-file, production-oriented command-line downloader for publicly
accessible media that the user is authorized to download.

Primary extraction engine:
    yt-dlp

Design goals:
    - No private-account access
    - No CAPTCHA bypass
    - No DRM circumvention
    - No browser-password extraction
    - No automatic authentication
    - No automatic execution of downloaded files
    - Safe filenames and paths
    - Batch downloads continue after individual failures
    - Structured logging
    - Optional JSON metadata
    - Dynamic format discovery
    - Best-effort public profile-photo resolution
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


APP_NAME = "Universal Media Downloader"
APP_VERSION = "1.0.0"

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DownloaderError(Exception):
    """Base application exception."""


class ConfigurationError(DownloaderError):
    """Invalid configuration."""


class DependencyError(DownloaderError):
    """Required dependency is missing."""


class UnsupportedPlatformError(DownloaderError):
    """The requested URL/platform is not supported."""


class ExtractionError(DownloaderError):
    """Media extraction failed."""


class DownloadError(DownloaderError):
    """Media download failed."""


class ProfileError(DownloaderError):
    """Profile resolution failed."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Platform(Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    THREADS = "threads"
    TWITTER = "twitter"
    TIKTOK = "tiktok"
    REDDIT = "reddit"
    PINTEREST = "pinterest"
    SNAPCHAT = "snapchat"
    TELEGRAM = "telegram"
    LINKEDIN = "linkedin"
    WHATSAPP = "whatsapp"
    VIMEO = "vimeo"
    TWITCH = "twitch"
    DAILYMOTION = "dailymotion"
    SOUNDCLOUD = "soundcloud"
    OTHER = "other"
    UNKNOWN = "unknown"


class ContentType(Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    PLAYLIST = "playlist"
    PROFILE = "profile"
    POST = "post"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    output_dir: Path = Path("downloads")
    log_dir: Path = Path("logs")
    retries: int = 3
    timeout: int = 30
    quality: str = "best"
    audio_only: bool = False
    write_metadata: bool = True
    verbose: bool = False
    debug: bool = False
    no_color: bool = False
    cookies_file: Optional[Path] = None
    cookies_from_browser: Optional[str] = None


@dataclass
class DetectedTarget:
    original_url: str
    normalized_url: str
    platform: Platform
    content_type: ContentType = ContentType.UNKNOWN
    is_profile_candidate: bool = False


@dataclass
class FormatInfo:
    format_id: str
    extension: str
    resolution: str
    height: Optional[int]
    width: Optional[int]
    fps: Optional[float]
    filesize: Optional[int]
    vcodec: str
    acodec: str
    format_note: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_video(self) -> bool:
        return self.vcodec not in ("", "none", None)

    @property
    def has_audio(self) -> bool:
        return self.acodec not in ("", "none", None)


@dataclass
class DownloadResult:
    success: bool
    url: str
    files: list[Path] = field(default_factory=list)
    error: Optional[str] = None
    skipped: bool = False


@dataclass
class BatchSummary:
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("universal_downloader")


class SecretFilter(logging.Filter):
    """Prevent obvious credential-like values from entering logs."""

    SECRET_PATTERNS = (
        re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(api[_-]?secret\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(access[_-]?token\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(authorization\s*:\s*)\S+"),
        re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in self.SECRET_PATTERNS:
            message = pattern.sub(r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(config: AppConfig) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if config.debug else (
        logging.INFO if config.verbose else logging.WARNING
    )

    LOGGER.setLevel(level)
    LOGGER.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        config.log_dir / "downloader.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretFilter())

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretFilter())

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(console_handler)
    
def clean_error_message(message: str) -> str:
    """Remove terminal color codes and normalize yt-dlp error text."""
    cleaned = ANSI_ESCAPE_RE.sub("", message).strip()

    if cleaned.upper().startswith("ERROR:"):
        cleaned = cleaned[6:].strip()

    return cleaned


def format_download_error(
    exc: Exception,
    platform: Optional[Platform] = None,
) -> str:
    message = clean_error_message(str(exc))

    if (
        platform == Platform.TIKTOK
        and "unable to extract universal data" in message.lower()
    ):
        return (
            f"{message}\n\n"
            "TikTok may be temporarily blocking automated access. Try:\n"
            "  • Wait a few minutes and retry\n"
            "  • Pass browser cookies: --cookies-from-browser edge\n"
            "  • Or export cookies to a file and pass: --cookies cookies.txt"
        )

    return message


def is_tiktok_rehydration_error(message: str) -> bool:
    lowered = clean_error_message(message).lower()
    return "unable to extract universal data" in lowered


TIKTOK_INTERNAL_RETRIES = 8
TIKTOK_RETRY_DELAYS = (1, 2, 3, 5, 8, 10, 12, 15)


def is_non_retryable_error(message: str) -> bool:
    message = clean_error_message(message).lower()

    permanent_markers = (
        "unable to extract webpage video data",
        "unable to extract webpage",
        "unsupported url",
        "private",
        "login required",
        "sign in",
        "authentication",
        "captcha",
        "http error 401",
        "http error 403",
        "http error 404",
        "http error 429",
        "too many requests",
        "rate limit",
        "video unavailable",
        "your ip address is blocked",
        "video not available",
    )

    return any(marker in message for marker in permanent_markers)


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def supports_color(config: AppConfig) -> bool:
    if config.no_color:
        return False
    return sys.stdout.isatty()


def ctext(text: str, code: str, config: AppConfig) -> str:
    if not supports_color(config):
        return text
    return f"\033[{code}m{text}\033[0m"


def success(text: str, config: AppConfig) -> None:
    print(ctext(f"✓ {text}", "32", config))


def failure(text: str, config: AppConfig) -> None:
    print(ctext(f"✗ {text}", "31", config))


def info(text: str, config: AppConfig) -> None:
    print(ctext(f"• {text}", "36", config))


def warning(text: str, config: AppConfig) -> None:
    print(ctext(f"! {text}", "33", config))


def print_banner(config: AppConfig) -> None:
    print()
    print("╔══════════════════════════════════════╗")
    print("║     Universal Media Downloader       ║")
    print(f"║              v{APP_VERSION:<14}     ║")
    print("╚══════════════════════════════════════╝")
    print()


# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------

def import_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError as exc:
        raise DependencyError(
            "Missing dependency: yt-dlp\n\n"
            "Install it with:\n"
            'python -m pip install "yt-dlp[default]==2026.8.19"'
        ) from exc


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def discover_js_runtimes() -> dict[str, dict[str, str]]:
    """Return installed JS runtimes for yt-dlp challenge solving."""
    runtimes: dict[str, dict[str, str]] = {}

    for name in ("node", "deno"):
        executable = shutil.which(name)
        if executable:
            runtimes[name] = {"path": executable}

    return runtimes


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def parse_dotenv(path: Path) -> dict[str, str]:
    """
    Small dependency-free .env parser.

    It intentionally supports only simple KEY=VALUE entries and does not
    execute shell syntax.
    """
    result: dict[str, str] = {}

    if not path.exists():
        return result

    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[7:].strip()

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {"'", '"'}
            ):
                value = value[1:-1]

            result[key] = value

    except OSError as exc:
        raise ConfigurationError(
            f"Could not read configuration file: {path}"
        ) from exc

    return result


def load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Could not read JSON configuration: {path}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigurationError("config.json must contain a JSON object.")

    return data


def env_value(
    dotenv: dict[str, str],
    key: str,
    default: Optional[str] = None,
) -> Optional[str]:
    return os.environ.get(key, dotenv.get(key, default))


def parse_config_int(
    value: Any,
    name: str,
    default: int,
) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"Invalid {name} value: {value!r}. Expected an integer."
        ) from exc


def build_config(args: argparse.Namespace) -> AppConfig:
    dotenv = parse_dotenv(Path(".env"))
    json_config = load_json_config(Path("config.json"))

    output_value = (
        args.output
        or env_value(dotenv, "DOWNLOAD_DIR")
        or json_config.get("download_dir")
        or "downloads"
    )

    retries_value = (
        args.retries
        if args.retries is not None
        else parse_config_int(
            env_value(dotenv, "RETRIES")
            or json_config.get("retries", 3),
            "retries",
            3,
        )
    )

    timeout_value = (
        args.timeout
        if args.timeout is not None
        else parse_config_int(
            env_value(dotenv, "TIMEOUT")
            or json_config.get("timeout", 30),
            "timeout",
            30,
        )
    )

    quality = (
        args.quality
        or env_value(dotenv, "QUALITY")
        or json_config.get("quality")
        or "best"
    )

    cookies_file_value = (
        args.cookies
        or env_value(dotenv, "COOKIES_FILE")
        or json_config.get("cookies_file")
    )

    cookies_browser_value = (
        args.cookies_from_browser
        or env_value(dotenv, "COOKIES_FROM_BROWSER")
        or json_config.get("cookies_from_browser")
    )

    config = AppConfig(
        output_dir=Path(output_value).expanduser(),
        log_dir=Path(
            env_value(dotenv, "LOG_DIR")
            or json_config.get("log_dir")
            or "logs"
        ).expanduser(),
        retries=max(0, retries_value),
        timeout=max(1, timeout_value),
        quality=quality,
        audio_only=args.audio_only,
        write_metadata=not args.no_metadata,
        verbose=args.verbose,
        debug=args.debug,
        no_color=args.no_color,
        cookies_file=(
            Path(cookies_file_value).expanduser()
            if cookies_file_value
            else None
        ),
        cookies_from_browser=(
            cookies_browser_value.strip()
            if cookies_browser_value
            else None
        ),
    )

    if config.retries > 20:
        raise ConfigurationError("Retries must not exceed 20.")

    if config.timeout > 3600:
        raise ConfigurationError("Timeout must not exceed 3600 seconds.")

    return config


# ---------------------------------------------------------------------------
# URL normalization and platform detection
# ---------------------------------------------------------------------------

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
}


def normalize_url(value: str) -> str:
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
    return urllib.parse.urlparse(url).hostname.lower().rstrip(".")  # type: ignore[union-attr]


TIKTOK_SHORT_DOMAINS = frozenset({"vt.tiktok.com", "vm.tiktok.com"})
TIKTOK_VIDEO_PATH_RE = re.compile(r"/video/\d+", re.IGNORECASE)


def resolve_url_redirect(url: str, timeout: int) -> str:
    """Follow HTTP redirects and return the final URL."""
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; "
                "UniversalMediaDownloader/1.0)"
            ),
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def normalize_tiktok_url(url: str, timeout: int = 30) -> str:
    """
    Resolve TikTok short links and strip tracking query parameters.

    TikTok share links often redirect to URLs with ?_r=...&_t=... tracking
    parameters that break yt-dlp extraction. The canonical video path alone
    is sufficient for public downloads.
    """
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


def domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith("." + candidate)


def detect_platform(url: str) -> Platform:
    normalized = normalize_url(url)
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
        # TikTok shortened URLs such as:
        #   https://vt.tiktok.com/ZSVkAuSQp/
        #   https://vm.tiktok.com/ZSHG5e6M4RYo4iO/
        # are video/share URLs, NOT profiles.
        domain = get_domain(url)

        if domain in {"vt.tiktok.com", "vm.tiktok.com"}:
            return ContentType.VIDEO

        if "/video/" in path:
            return ContentType.VIDEO

        if path.startswith("/@"):
            segments = [s for s in path.split("/") if s]

            # /@username is a profile.
            if len(segments) == 1:
                return ContentType.PROFILE

            # /@username/video/<id>
            if len(segments) >= 3 and segments[1].lower() == "video":
                return ContentType.VIDEO

        return ContentType.UNKNOWN

    if platform == Platform.FACEBOOK:
        if "/watch" in path or "/reel" in path or "/videos/" in path:
            return ContentType.VIDEO
        if "/profile.php" in path or "/people/" in path:
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

    if platform == Platform.SOUNDCLOUD:
        return ContentType.AUDIO

    if platform == Platform.DAILYMOTION:
        return ContentType.VIDEO

    return ContentType.UNKNOWN


def detect_target(url: str, timeout: int = 30) -> DetectedTarget:
    normalized = normalize_url(url)
    platform = detect_platform(normalized)

    if platform == Platform.TIKTOK:
        normalized = normalize_tiktok_url(normalized, timeout=timeout)

    content_type = detect_content_type(normalized, platform)

    return DetectedTarget(
        original_url=url,
        normalized_url=normalized,
        platform=platform,
        content_type=content_type,
        is_profile_candidate=content_type == ContentType.PROFILE,
    )


# ---------------------------------------------------------------------------
# Filename and filesystem management
# ---------------------------------------------------------------------------

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
    name = html.unescape(name or "")
    name = INVALID_FILENAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")

    if not name:
        name = fallback

    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = "_" + name

    # Avoid excessively long individual filenames.
    return name[:180].rstrip(" .") or fallback


def preferred_media_filename(info: dict[str, Any]) -> Optional[str]:
    """
    Build ``uploader_uploader_id_id.ext`` from download metadata.

    Falls back to ``unknown`` for missing uploader or uploader_id values.
    """
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
    """Rename a downloaded file to the preferred metadata-based filename."""
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


def ensure_inside_directory(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()

    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise DownloadError(
            "Refusing to write outside the configured download directory."
        ) from exc

    return candidate_resolved


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for index in range(1, 100000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate

    raise DownloadError(
        f"Could not create a unique filename for: {path.name}"
    )


def platform_directory(platform: Platform) -> str:
    if platform == Platform.TWITTER:
        return "twitter"
    return platform.value


# ---------------------------------------------------------------------------
# Progress hook
# ---------------------------------------------------------------------------

def human_size(value: Optional[float]) -> str:
    if value is None:
        return "unknown"

    value = float(value)

    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if abs(value) < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} PB"


def human_speed(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return f"{human_size(value)}/s"


def human_eta(seconds: Optional[int]) -> str:
    if seconds is None:
        return "unknown"

    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class ProgressRenderer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.last_percent = -1

    def reset(self) -> None:
        self.last_percent = -1

    def clear_line(self) -> None:
        if self.last_percent >= 0:
            print("\r" + " " * 100 + "\r", end="", flush=True)
            self.last_percent = -1

    def __call__(self, data: dict[str, Any]) -> None:
        status = data.get("status")

        if status == "downloading":
            downloaded = data.get("downloaded_bytes", 0) or 0
            total = (
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
            )

            if total:
                percent = downloaded / total * 100
                bar_width = 30
                filled = int(bar_width * percent / 100)
                bar = "█" * filled + "░" * (bar_width - filled)

                print(
                    f"\r{bar} {percent:6.2f}% "
                    f"| {human_size(downloaded)}/{human_size(total)} "
                    f"| {human_speed(data.get('speed'))} "
                    f"| ETA {human_eta(data.get('eta'))}",
                    end="",
                    flush=True,
                )
                self.last_percent = int(percent)

        elif status == "finished":
            self.clear_line()
            print("Processing downloaded file...")


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def safe_json_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple)):
        return [safe_json_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): safe_json_value(val)
            for key, val in value.items()
        }

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
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return metadata_path
    except OSError:
        LOGGER.exception("Unable to write metadata: %s", metadata_path)
        return None


# ---------------------------------------------------------------------------
# Format handling
# ---------------------------------------------------------------------------

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
        fmt.height
        for fmt in formats
        if fmt.has_video and fmt.height
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
) -> str:
    quality = quality.strip().lower()

    if audio_only or quality in {"audio", "audio-only"}:
        return "bestaudio/best"

    if quality in {"best", "maximum", "max"}:
        # Prefer a combined format where possible, otherwise let FFmpeg merge
        # best video + best audio.
        return "bestvideo*+bestaudio/best"

    match = re.fullmatch(r"(\d{3,4})p", quality)

    if match:
        height = int(match.group(1))

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


# ---------------------------------------------------------------------------
# yt-dlp extraction
# ---------------------------------------------------------------------------

class YTDLPLogger:
    """Route yt-dlp log output through the application logger."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def debug(self, message: str) -> None:
        if self.config.debug:
            LOGGER.debug(clean_error_message(message))

    def info(self, message: str) -> None:
        if self.config.verbose:
            LOGGER.info(clean_error_message(message))

    def warning(self, message: str) -> None:
        LOGGER.warning(clean_error_message(message))

    def error(self, message: str) -> None:
        # yt-dlp reports handled failures as errors; keep them off stderr.
        LOGGER.debug(clean_error_message(message))


class YTDLPExtractor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.yt_dlp = import_yt_dlp()

    def base_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": not self.config.verbose,
            "noprogress": True,
            "socket_timeout": self.config.timeout,
            "retries": 0,
            "fragment_retries": 0,
            "continuedl": True,
            "noplaylist": False,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "overwrites": False,
            "logger": YTDLPLogger(self.config),
            "no_color": self.config.no_color,
        }

        js_runtimes = discover_js_runtimes()
        if js_runtimes:
            options["js_runtimes"] = js_runtimes

        if self.config.cookies_file:
            options["cookiefile"] = str(self.config.cookies_file)

        if self.config.cookies_from_browser:
            options["cookiesfrombrowser"] = (
                self.config.cookies_from_browser,
            )

        return options

    def platform_extra_options(self, platform: Platform) -> dict[str, Any]:
        if platform == Platform.TIKTOK:
            return {
                "extractor_retries": 2,
                "sleep_interval_requests": 1,
            }

        return {}

    def extract_info(
        self,
        url: str,
        download: bool = False,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        options = self.base_options()

        if extra:
            options.update(extra)

        LOGGER.debug("Extracting URL: %s", url)

        try:
            with self.yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)

            if not isinstance(info, dict):
                raise ExtractionError(
                    "The extractor returned no usable metadata."
                )

            return info

        except self.yt_dlp.utils.DownloadError as exc:
            raise ExtractionError(clean_error_message(str(exc))) from exc
        except Exception as exc:
            LOGGER.exception("Unexpected extraction failure.")
            raise ExtractionError(clean_error_message(str(exc))) from exc

    def download(
        self,
        url: str,
        output_template: str,
        format_selector: str,
        progress_hook: Callable[[dict[str, Any]], None],
        platform: Platform = Platform.UNKNOWN,
    ) -> dict[str, Any]:
        options = self.base_options()
        options.update(self.platform_extra_options(platform))

        options.update(
            {
                "format": format_selector,
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "retries": 0,
                "fragment_retries": 0,
                "ignoreerrors": False,
                "writethumbnail": False,
                "writeinfojson": False,
            }
        )

        wants_audio_extract = (
            self.config.audio_only
            or self.config.quality.strip().lower() in {"audio", "audio-only"}
        )

        if wants_audio_extract:
            if not check_ffmpeg():
                raise DependencyError(
                    "FFmpeg is required for reliable audio extraction.\n\n"
                    "Please install FFmpeg and ensure it is available in PATH."
                )

            options.update(
                {
                    "format": "bestaudio/best",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )

        elif "+" in format_selector and not check_ffmpeg():
            raise DependencyError(
                "FFmpeg is required to merge separate audio/video streams.\n\n"
                "Please install FFmpeg and ensure it is available in PATH."
            )

        LOGGER.info(
            "Downloading URL=%s format=%s",
            url,
            format_selector,
        )

        try:
            with self.yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)

            if not isinstance(info, dict):
                raise DownloadError(
                    "yt-dlp did not return download metadata."
                )

            return info

        except self.yt_dlp.utils.DownloadError as exc:
            raise DownloadError(clean_error_message(str(exc))) from exc
        except Exception as exc:
            LOGGER.exception("Unexpected download failure.")
            raise DownloadError(clean_error_message(str(exc))) from exc


# ---------------------------------------------------------------------------
# Public profile image resolver
# ---------------------------------------------------------------------------

def extract_meta_image(html_text: str) -> Optional[str]:
    """
    Extracts only publicly exposed HTML metadata.

    This does not attempt JavaScript execution, login, cookies, CAPTCHA
    solving, private endpoints, or hidden API calls.
    """

    patterns = [
        re.compile(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            re.I,
        ),
        re.compile(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
            re.I,
        ),
        re.compile(
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            re.I,
        ),
        re.compile(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image',
            re.I,
        ),
    ]

    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            return html.unescape(match.group(1))

    return None


def fetch_public_html(
    url: str,
    timeout: int,
) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; "
                "UniversalMediaDownloader/1.0)"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise ProfileError(
            f"Public profile page returned HTTP {exc.code}."
        ) from exc
    except urllib.error.URLError as exc:
        raise ProfileError(
            f"Could not access public profile page: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ProfileError("Profile request timed out.") from exc


def extract_thumbnail_candidates(info: dict[str, Any]) -> list[str]:
    candidates: list[str] = []

    direct_keys = (
        "channel_thumbnail",
        "uploader_thumbnail",
        "creator_thumbnail",
        "thumbnail",
    )

    for key in direct_keys:
        value = info.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    thumbnails = info.get("thumbnails")

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

    # Remove duplicates while preserving order.
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

    allowed = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".avif",
    }

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
                "Mozilla/5.0 (compatible; "
                "UniversalMediaDownloader/1.0)"
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
    """
    Best-effort resolver.

    It only uses:
      1. Metadata returned by yt-dlp.
      2. Public HTML metadata such as og:image.

    It does not authenticate or bypass restrictions.
    """

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

        info(
            f"Platform: {platform.value}",
            self.config,
        )
        info("Resolving publicly exposed profile image...", self.config)

        candidates: list[str] = []

        # First attempt: yt-dlp metadata.
        try:
            extracted = self.extractor.extract_info(
                target.normalized_url,
                download=False,
                extra={
                    "skip_download": True,
                    "extract_flat": False,
                },
            )
            candidates.extend(extract_thumbnail_candidates(extracted))
        except ExtractionError as exc:
            LOGGER.info(
                "yt-dlp profile metadata unavailable: %s",
                exc,
            )

        # Second attempt: public HTML metadata.
        try:
            page = fetch_public_html(
                target.normalized_url,
                self.config.timeout,
            )
            meta_image = extract_meta_image(page)

            if meta_image:
                candidates.append(
                    urllib.parse.urljoin(
                        target.normalized_url,
                        meta_image,
                    )
                )
        except ProfileError as exc:
            LOGGER.info(
                "Public HTML profile lookup failed: %s",
                exc,
            )

        # Deduplicate.
        unique_candidates: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            if candidate.startswith(("http://", "https://")):
                if candidate not in seen:
                    seen.add(candidate)
                    unique_candidates.append(candidate)

        if not unique_candidates:
            raise ProfileError(
                "No publicly exposed profile image could be resolved. "
                "The profile may require authentication, may be private, "
                "or may not expose its profile image through public metadata."
            )

        username = (
            username_hint
            or extract_username_from_profile_url(
                target.normalized_url,
                platform,
            )
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

        # Security boundary.
        destination = ensure_inside_directory(
            self.config.output_dir,
            destination,
        )

        for image_url in unique_candidates:
            try:
                saved = download_public_image(
                    image_url,
                    destination,
                    self.config.timeout,
                    self.config.output_dir,
                )
                return saved
            except Exception as exc:
                LOGGER.info(
                    "Profile image candidate failed: %s",
                    exc,
                )

        raise ProfileError(
            "A public image URL was found, but it could not be downloaded."
        )


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


# ---------------------------------------------------------------------------
# Download engine
# ---------------------------------------------------------------------------

class DownloadEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.extractor = YTDLPExtractor(config)
        self.profile_resolver = ProfilePhotoResolver(
            config,
            self.extractor,
        )

    def choose_output_template(
        self,
        target: DetectedTarget,
    ) -> str:
        base = (
            self.config.output_dir
            / platform_directory(target.platform)
        )

        base.mkdir(parents=True, exist_ok=True)

        # yt-dlp performs its own output sanitization. The final security
        # boundary is still our configured output directory.
        return str(
            base
            # / "%(title).180B [%(id)s].%(ext)s"
            / "%(uploader)s_%(uploader_id)s_%(id)s.%(ext)s"
        )

    def inspect(
        self,
        url: str,
        platform: Platform = Platform.UNKNOWN,
    ) -> dict[str, Any]:
        return self.extractor.extract_info(
            url,
            download=False,
            extra={
                "skip_download": True,
                **self.extractor.platform_extra_options(platform),
            },
        )

    def download_once(
        self,
        target: DetectedTarget,
    ) -> DownloadResult:
        if target.platform == Platform.WHATSAPP:
            raise UnsupportedPlatformError(
                "WhatsApp is not implemented as a private-client downloader. "
                "No session, private chat, or authentication circumvention "
                "is attempted."
            )

        if target.platform == Platform.UNKNOWN:
            warning(
                "Unknown domain; attempting yt-dlp generic extraction.",
                self.config,
            )

        if target.content_type == ContentType.PROFILE:
            warning(
                "This appears to be a profile URL. "
                "Use --profile for profile-picture mode.",
                self.config,
            )

        output_template = self.choose_output_template(target)

        selector = quality_to_selector(
            self.config.quality,
            self.config.audio_only,
        )

        progress = ProgressRenderer(self.config)

        downloaded_info = self._download_media(
            target,
            output_template,
            selector,
            progress,
        )

        files: list[Path] = []

        requested = downloaded_info.get("requested_downloads")

        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict):
                    filepath = item.get("filepath")
                    if filepath:
                        files.append(Path(filepath))

        filepath = downloaded_info.get("_filename")
        if filepath:
            files.append(Path(filepath))

        # Fall back to inspecting the output directory when yt-dlp did not
        # expose the filename through the returned dictionary.
        if not files:
            output_dir = self.config.output_dir / platform_directory(
                target.platform
            )

            if output_dir.exists():
                candidates = sorted(
                    (
                        path
                        for path in output_dir.iterdir()
                        if path.is_file()
                        and not path.name.endswith(".json")
                        and not path.name.endswith(".part")
                    ),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )

                if candidates:
                    files.append(candidates[0])

        # Deduplicate and retain existing files.
        unique_files: list[Path] = []
        seen: set[str] = set()

        for path in files:
            try:
                resolved = path.resolve()
            except OSError:
                continue

            key = str(resolved)

            if key in seen:
                continue

            seen.add(key)

            if resolved.exists():
                unique_files.append(resolved)

        if not unique_files:
            raise DownloadError(
                "yt-dlp reported success but no output file could be located."
            )

        renamed_files: list[Path] = []

        for path in unique_files:
            renamed_files.append(
                rename_media_file(
                    path,
                    downloaded_info,
                    self.config.output_dir,
                )
            )

        unique_files = renamed_files

        for path in unique_files:
            # Final path security check.
            ensure_inside_directory(
                self.config.output_dir,
                path,
            )

            if self.config.write_metadata:
                write_metadata_file(
                    path,
                    downloaded_info,
                    target.normalized_url,
                )

        return DownloadResult(
            success=True,
            url=target.normalized_url,
            files=unique_files,
        )

    def _download_media(
        self,
        target: DetectedTarget,
        output_template: str,
        selector: str,
        progress: ProgressRenderer,
    ) -> dict[str, Any]:
        if target.platform != Platform.TIKTOK:
            return self.extractor.download(
                target.normalized_url,
                output_template,
                selector,
                progress,
                platform=target.platform,
            )

        last_error: Optional[DownloadError] = None

        for attempt in range(TIKTOK_INTERNAL_RETRIES):
            try:
                progress.reset()
                return self.extractor.download(
                    target.normalized_url,
                    output_template,
                    selector,
                    progress,
                    platform=target.platform,
                )
            except DownloadError as exc:
                last_error = exc

                if not is_tiktok_rehydration_error(str(exc)):
                    raise

                if attempt >= TIKTOK_INTERNAL_RETRIES - 1:
                    break

                delay = TIKTOK_RETRY_DELAYS[
                    min(attempt, len(TIKTOK_RETRY_DELAYS) - 1)
                ]
                delay += random.uniform(0.25, 1.25)
                progress.clear_line()
                LOGGER.info(
                    "TikTok access blocked (attempt %d/%d); "
                    "retrying in %ds",
                    attempt + 1,
                    TIKTOK_INTERNAL_RETRIES,
                    delay,
                )
                time.sleep(delay)

        if last_error:
            raise last_error

        raise DownloadError("TikTok download failed for an unknown reason.")

    def download(
        self,
        url: str,
    ) -> DownloadResult:
        target = detect_target(url, timeout=self.config.timeout)

        LOGGER.info(
            "Target detected platform=%s type=%s url=%s",
            target.platform.value,
            target.content_type.value,
            target.normalized_url,
        )

        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.retries + 2):
            try:
                return self.download_once(target)

            except (
                DownloadError,
                ExtractionError,
                DependencyError,
            ) as exc:
                last_error = exc
                message = clean_error_message(str(exc))

                if is_non_retryable_error(message):
                    break

                if (
                    target.platform == Platform.TIKTOK
                    and is_tiktok_rehydration_error(message)
                ):
                    break

                if attempt > self.config.retries:
                    break

                delay = min(2 ** (attempt - 1), 15)

                if self.config.verbose:
                    warning(
                        f"Transient failure. Retry "
                        f"{attempt}/{self.config.retries} in {delay}s...",
                        self.config,
                    )

                LOGGER.warning(
                    "Download attempt %d failed: %s",
                    attempt,
                    exc,
                )

                time.sleep(delay)

            except UnsupportedPlatformError:
                raise

            except Exception as exc:
                LOGGER.exception("Unexpected download failure.")
                last_error = exc
                break

        if last_error:
            raise last_error

        raise DownloadError("Download failed for an unknown reason.")

    def download_profile(
        self,
        profile_value: str,
    ) -> Path:
        profile_url = resolve_profile_input(profile_value)

        target = detect_target(profile_url, timeout=self.config.timeout)

        if target.platform in {
            Platform.UNKNOWN,
            Platform.WHATSAPP,
        }:
            raise ProfileError(
                "The supplied profile cannot be resolved safely."
            )

        username = extract_username_from_profile_url(
            target.normalized_url,
            target.platform,
        )

        return self.profile_resolver.resolve(
            target.normalized_url,
            target.platform,
            username,
        )


# ---------------------------------------------------------------------------
# Profile input
# ---------------------------------------------------------------------------

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
}


def resolve_profile_input(value: str) -> str:
    value = value.strip()

    if not value:
        raise ProfileError("Profile value is empty.")

    # A URL is unambiguous.
    if (
        "://" in value
        or value.startswith("www.")
        or "." in value.split("/")[0]
    ):
        return normalize_url(value)

    # Bare @username is inherently ambiguous. Refuse to guess.
    if value.startswith("@"):
        raise ProfileError(
            "A bare @username is ambiguous. "
            "Provide the platform profile URL, for example:\n"
            "https://www.instagram.com/username/"
        )

    # Support explicit platform:username syntax.
    if ":" in value:
        prefix, username = value.split(":", 1)

        platform = USERNAME_PLATFORM_PREFIXES.get(
            prefix.strip().lower()
        )

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
            }

            domain = domain_map[platform]

            if platform == Platform.REDDIT:
                return normalize_url(
                    f"https://{domain}/{username}/"
                )

            if platform == Platform.YOUTUBE:
                return normalize_url(
                    f"https://{domain}{username}"
                )

            return normalize_url(
                f"https://{domain}/{username}/"
            )

    raise ProfileError(
        "A bare username is ambiguous. Use platform:username, "
        "for example:\n"
        "  instagram:username\n"
        "  tiktok:username\n"
        "  x:username\n"
        "or provide the complete public profile URL."
    )


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def read_batch_file(path: Path) -> list[str]:
    if not path.exists():
        raise DownloaderError(f"Batch file does not exist: {path}")

    if not path.is_file():
        raise DownloaderError(f"Batch path is not a file: {path}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DownloaderError(
            f"Could not read batch file: {path}"
        ) from exc

    urls: list[str] = []

    for line in lines:
        value = line.strip()

        if not value or value.startswith("#"):
            continue

        urls.append(value)

    return urls


def run_batch(
    engine: DownloadEngine,
    urls: list[str],
) -> BatchSummary:
    summary = BatchSummary()

    for index, url in enumerate(urls, start=1):
        print()
        print("=" * 70)
        print(f"[{index}/{len(urls)}] {url}")
        print("=" * 70)

        try:
            result = engine.download(url)

            if result.skipped:
                summary.skipped += 1
                warning("Skipped.", engine.config)
            else:
                summary.successful += 1

                success("Download completed.", engine.config)

                for path in result.files:
                    print(f"  → {path}")

        except Exception as exc:
            summary.failed += 1
            summary.failures.append((url, str(exc)))
            failure(f"Download failed: {exc}", engine.config)
            LOGGER.exception("Batch item failed: %s", url)

    return summary


def print_batch_summary(
    summary: BatchSummary,
    config: AppConfig,
) -> None:
    print()
    print("Download Summary")
    print("----------------")
    print(f"✓ Successful: {summary.successful}")
    print(f"✗ Failed:     {summary.failed}")
    print(f"⊘ Skipped:    {summary.skipped}")

    if summary.failures:
        print()
        print("Failed:")

        for index, (url, reason) in enumerate(
            summary.failures,
            start=1,
        ):
            print(f"{index}. {url}")
            print(f"   {reason}")


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def interactive_mode(
    engine: DownloadEngine,
) -> int:
    config = engine.config

    print_banner(config)

    while True:
        try:
            value = input(
                "Enter URL, profile URL, platform:username, "
                "or 'q' to quit:\n> "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if value.lower() in {"q", "quit", "exit"}:
            return 0

        if not value:
            continue

        try:
            if ":" in value and "://" not in value:
                # Explicit profile syntax such as instagram:user.
                prefix = value.split(":", 1)[0].lower()

                if prefix in USERNAME_PLATFORM_PREFIXES:
                    saved = engine.download_profile(value)
                    success(
                        f"Profile picture saved: {saved}",
                        config,
                    )
                    continue

            target = detect_target(value, timeout=config.timeout)

            print()
            print(f"Platform:     {target.platform.value}")
            print(f"Content type: {target.content_type.value}")

            try:
                info_data = engine.inspect(
                    target.normalized_url,
                    platform=target.platform,
                )
            except ExtractionError as exc:
                warning(
                    f"Could not inspect formats: {exc}",
                    config,
                )
                info_data = {}

            if info_data:
                formats = parse_format(info_data)
                heights = unique_video_heights(formats)

                if heights:
                    print()
                    print("Available qualities:")

                    print("1. Best")

                    for number, height in enumerate(
                        heights[:8],
                        start=2,
                    ):
                        print(f"{number}. {height}p")

                    print(f"{len(heights) + 2}. Audio only")

                    selection = input("Select [1]: ").strip()

                    if not selection:
                        config.quality = "best"
                        config.audio_only = False
                    elif selection == "1":
                        config.quality = "best"
                        config.audio_only = False
                    elif selection == str(len(heights) + 2):
                        config.audio_only = True
                        config.quality = "audio"
                    else:
                        try:
                            selected_index = int(selection) - 2

                            if 0 <= selected_index < len(heights):
                                config.quality = (
                                    f"{heights[selected_index]}p"
                                )
                                config.audio_only = False
                            else:
                                warning(
                                    "Invalid selection; using best quality.",
                                    config,
                                )
                                config.quality = "best"
                                config.audio_only = False

                        except ValueError:
                            warning(
                                "Invalid selection; using best quality.",
                                config,
                            )
                            config.quality = "best"
                            config.audio_only = False

            result = engine.download(target.normalized_url)

            success("Download completed.", config)

            for path in result.files:
                print(f"Saved: {path}")

        except Exception as exc:
            failure(str(exc), config)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="downloader.py",
        description=(
            "Universal Media Downloader for publicly accessible media "
            "that the user is authorized to download."
        ),
        epilog=(
            "This application does not bypass authentication, CAPTCHAs, "
            "DRM, private profiles, or technical access restrictions."
        ),
    )

    parser.add_argument(
        "url",
        nargs="?",
        help="Media, post, playlist, or public profile URL.",
    )

    parser.add_argument(
        "--url",
        dest="url_option",
        help="Media URL. Equivalent to positional URL.",
    )

    parser.add_argument(
        "--batch",
        type=Path,
        help="Read URLs from a text file.",
    )

    parser.add_argument(
        "--profile",
        help=(
            "Download a publicly exposed profile image from a public "
            "profile URL or platform:username."
        ),
    )

    parser.add_argument(
        "--cookies",
        type=Path,
        help="Netscape-format cookies file for authenticated downloads.",
    )

    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help=(
            "Load cookies from a browser profile, for example: "
            "chrome, edge, firefox, brave."
        ),
    )

    parser.add_argument(
        "--output",
        help="Output directory. Default: downloads",
    )

    parser.add_argument(
        "--quality",
        default=None,
        help=(
            "Quality: best, 2160p, 1440p, 1080p, 720p, 480p, "
            "audio, or an explicit yt-dlp selector."
        ),
    )

    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio as MP3.",
    )

    parser.add_argument(
        "--formats",
        metavar="URL",
        help="List formats available for a URL without downloading.",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=None,
        help="Number of retries for transient failures. Default: 3.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Network timeout in seconds. Default: 30.",
    )

    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not save .json metadata alongside downloads.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable informational logging.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable terminal colors.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"{APP_NAME}\n"
            f"Version: {APP_VERSION}\n"
            f"Python: {platform_python_version()}"
        ),
    )

    return parser


def platform_python_version() -> str:
    return sys.version.split()[0]


def validate_url_option(args: argparse.Namespace) -> Optional[str]:
    if args.url and args.url_option:
        raise ConfigurationError(
            "Specify either a positional URL or --url, not both."
        )

    return args.url or args.url_option


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = build_config(args)
        configure_logging(config)

        engine = DownloadEngine(config)

        requested_url = validate_url_option(args)

        # Formats mode.
        if args.formats:
            target = detect_target(args.formats, timeout=config.timeout)

            print_banner(config)
            print(f"URL:      {target.normalized_url}")
            print(f"Platform: {target.platform.value}")
            print()

            info_data = engine.inspect(
                target.normalized_url,
                platform=target.platform,
            )

            print(f"Title: {info_data.get('title') or 'unknown'}")
            print_formats(info_data, config)

            return 0

        # Profile mode.
        if args.profile:
            print_banner(config)

            saved = engine.download_profile(args.profile)

            success(
                f"Profile picture saved: {saved}",
                config,
            )

            return 0

        # Batch mode.
        if args.batch:
            urls = read_batch_file(args.batch)

            if not urls:
                warning(
                    "The batch file contains no URLs.",
                    config,
                )
                return 0

            print_banner(config)

            summary = run_batch(engine, urls)
            print_batch_summary(summary, config)

            return 1 if summary.failed else 0

        # Explicit URL.
        if requested_url:
            print_banner(config)

            try:
                target = detect_target(requested_url, timeout=config.timeout)

                print(f"URL:      {target.normalized_url}")
                print(f"Platform: {target.platform.value}")
                print(f"Type:     {target.content_type.value}")
                print()

                info("Downloading...", config)

                result = engine.download(
                    target.normalized_url,
                )

                success("Download completed.", config)

                for path in result.files:
                    print(f"Saved: {path}")

                return 0

            except (
                DownloadError,
                ExtractionError,
                UnsupportedPlatformError,
                ProfileError,
                DependencyError,
            ) as exc:
                failure(
                    f"Download failed\n\nReason:\n"
                    f"{format_download_error(exc, target.platform)}",
                    config,
                )

                LOGGER.error(
                    "Single URL download failed: %s - %s",
                    requested_url,
                    exc,
                )

                return 1

            except Exception as exc:
                failure(
                    f"Download failed\n\nReason:\n{exc}",
                    config,
                )

                LOGGER.exception(
                    "Single URL download failed: %s",
                    requested_url,
                )

                return 1

        # Interactive mode.
        return interactive_mode(engine)

    except DependencyError as exc:
        print(f"✗ Missing dependency\n\n{exc}", file=sys.stderr)
        return 2

    except ConfigurationError as exc:
        print(f"✗ Configuration error\n\n{exc}", file=sys.stderr)
        return 2

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130

    except Exception as exc:
        print(
            f"✗ Unexpected application error\n\n{exc}",
            file=sys.stderr,
        )
        LOGGER.exception("Unexpected application error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


