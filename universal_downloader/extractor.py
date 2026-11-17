"""yt-dlp wrapper, dependency inspection, and download pipeline configuration."""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Callable, Optional

from universal_downloader.exceptions import DependencyError, DownloadError, ExtractionError
from universal_downloader.logging_utils import clean_error_message
from universal_downloader.models import AppConfig, Platform

LOGGER = logging.getLogger("universal_downloader")


def import_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError as exc:
        raise DependencyError(
            "Missing dependency: yt-dlp\n\n"
            "Install it with:\n"
            'python -m pip install "yt-dlp[default]"'
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


def parse_rate_limit(rate_str: Optional[str]) -> Optional[int]:
    """Parse strings like '5M', '500K', '1024' into bytes per second."""
    if not rate_str:
        return None
    rate_str = rate_str.strip().upper()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGT]?B?)?$", rate_str)
    if not match:
        return None
    val, unit = match.groups()
    multiplier = 1
    if unit:
        prefix = unit[0]
        if prefix == "K":
            multiplier = 1024
        elif prefix == "M":
            multiplier = 1024 ** 2
        elif prefix == "G":
            multiplier = 1024 ** 3
        elif prefix == "T":
            multiplier = 1024 ** 4
    return int(float(val) * multiplier)


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
            browser_spec = self.config.cookies_from_browser
            if ":" in browser_spec:
                browser_name, profile = browser_spec.split(":", 1)
                options["cookiesfrombrowser"] = (browser_name.strip(), profile.strip())
            else:
                options["cookiesfrombrowser"] = (browser_spec,)

        if self.config.proxy:
            options["proxy"] = self.config.proxy

        if self.config.geo_bypass:
            options["geo_bypass"] = True

        if self.config.download_archive:
            options["download_archive"] = str(self.config.download_archive)

        rate_limit = parse_rate_limit(self.config.limit_rate)
        if rate_limit:
            options["ratelimit"] = rate_limit

        if self.config.playlist_items:
            options["playlist_items"] = self.config.playlist_items

        if self.config.max_downloads:
            options["max_downloads"] = self.config.max_downloads

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
                raise ExtractionError("The extractor returned no usable metadata.")

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

        postprocessors: list[dict[str, Any]] = []

        options.update(
            {
                "format": format_selector,
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "retries": 0,
                "fragment_retries": 0,
                "ignoreerrors": False,
                "writethumbnail": self.config.embed_thumbnail,
                "writeinfojson": False,
            }
        )

        wants_audio = (
            self.config.audio_only
            or self.config.quality.strip().lower() in {"audio", "audio-only"}
        )

        if wants_audio:
            if not check_ffmpeg():
                raise DependencyError(
                    "FFmpeg is required for audio extraction.\n\n"
                    "Please install FFmpeg and ensure it is available in PATH."
                )

            options["format"] = "bestaudio/best"

            if self.config.audio_format != "best":
                postprocessors.append(
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": self.config.audio_format,
                        "preferredquality": self.config.audio_quality,
                    }
                )

        elif "+" in format_selector and not check_ffmpeg():
            raise DependencyError(
                "FFmpeg is required to merge separate audio/video streams.\n\n"
                "Please install FFmpeg and ensure it is available in PATH."
            )

        # Metadata embedding
        if self.config.embed_metadata:
            if not check_ffmpeg():
                raise DependencyError("FFmpeg is required for embedding metadata.")
            postprocessors.append(
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                    "add_chapters": True,
                }
            )

        # Thumbnail embedding
        if self.config.embed_thumbnail:
            if not check_ffmpeg():
                raise DependencyError("FFmpeg is required for embedding thumbnails.")
            postprocessors.append(
                {
                    "key": "EmbedThumbnail",
                    "already_have_thumbnail": False,
                }
            )

        # Subtitles configuration
        if self.config.write_subs or self.config.embed_subs or self.config.auto_subs:
            options["writesubtitles"] = self.config.write_subs or self.config.embed_subs
            if self.config.auto_subs:
                options["writeautomaticsub"] = True

            if self.config.sub_langs:
                options["subtitleslangs"] = [
                    lang.strip()
                    for lang in self.config.sub_langs.split(",")
                    if lang.strip()
                ]
            else:
                options["subtitleslangs"] = ["all", "-live_chat"]

            if self.config.embed_subs:
                if not check_ffmpeg():
                    raise DependencyError("FFmpeg is required to embed subtitles.")
                postprocessors.append(
                    {
                        "key": "FFmpegEmbedSubtitle",
                    }
                )

        # Video remuxing
        if self.config.remux_video and not wants_audio:
            if not check_ffmpeg():
                raise DependencyError("FFmpeg is required for remuxing video containers.")
            postprocessors.append(
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": self.config.remux_video,
                }
            )

        # Chapter splitting
        if self.config.split_chapters:
            if not check_ffmpeg():
                raise DependencyError("FFmpeg is required for chapter splitting.")
            postprocessors.append(
                {
                    "key": "FFmpegSplitChapters",
                }
            )

        # SponsorBlock removal
        if self.config.sponsorblock_remove:
            categories = [
                c.strip()
                for c in self.config.sponsorblock_remove.split(",")
                if c.strip()
            ]
            postprocessors.append(
                {
                    "key": "SponsorBlock",
                    "categories": set(categories),
                    "when": "after_filter",
                }
            )
            postprocessors.append(
                {
                    "key": "ModifyChapters",
                    "remove_sponsor_segments": set(categories),
                }
            )

        if postprocessors:
            options["postprocessors"] = postprocessors

        LOGGER.info(
            "Downloading URL=%s format=%s",
            url,
            format_selector,
        )

        try:
            with self.yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)

            if not isinstance(info, dict):
                raise DownloadError("yt-dlp did not return download metadata.")

            return info

        except self.yt_dlp.utils.DownloadError as exc:
            raise DownloadError(clean_error_message(str(exc))) from exc
        except Exception as exc:
            LOGGER.exception("Unexpected download failure.")
            raise DownloadError(clean_error_message(str(exc))) from exc
