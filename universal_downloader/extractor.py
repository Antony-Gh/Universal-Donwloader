"""yt-dlp wrapper, dependency inspection, and download pipeline configuration."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from universal_downloader.exceptions import DependencyError, DownloadError, ExtractionError
from universal_downloader.ffmpeg_manager import (
    ensure_ffmpeg,
    find_ffmpeg,
    find_ffprobe,
    is_ffmpeg_available,
)
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
    return is_ffmpeg_available()


def check_ffprobe() -> bool:
    return find_ffprobe() is not None


def discover_js_runtimes() -> dict[str, dict[str, str]]:
    """Return installed JS runtimes for yt-dlp challenge solving."""
    runtimes: dict[str, dict[str, str]] = {}
    for name in ("node", "deno"):
        executable = shutil.which(name)
        if executable:
            runtimes[name] = {"path": executable}
    return runtimes


def parse_timestamp_seconds(val: Optional[str]) -> Optional[float]:
    """Convert timestamp strings like '01:30:15', '03:15', or '90' to seconds."""
    if not val:
        return None
    val = val.strip().lstrip("*")
    try:
        parts = val.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 1:
            return float(parts[0])
    except ValueError:
        return None
    return None


_HUMAN_DURATION_RE = re.compile(
    r"^\s*(?:(?P<h>\d+(?:\.\d+)?)\s*h)?\s*(?:(?P<m>\d+(?:\.\d+)?)\s*m)?\s*(?:(?P<s>\d+(?:\.\d+)?)\s*s)?\s*$",
    re.IGNORECASE,
)


def parse_duration_seconds(val: Optional[str]) -> Optional[float]:
    """Parse recording duration specs like '00:10:00', '5:00', '300', '5m', or '1h30m' into positive seconds."""
    if not val:
        return None
    raw = str(val).strip()
    if not raw:
        return None

    seconds = parse_timestamp_seconds(raw)
    if seconds is None:
        match = _HUMAN_DURATION_RE.match(raw)
        if match and any(match.group(k) for k in ("h", "m", "s")):
            hours = float(match.group("h") or 0)
            minutes = float(match.group("m") or 0)
            secs = float(match.group("s") or 0)
            seconds = hours * 3600 + minutes * 60 + secs

    if seconds is None or seconds <= 0:
        raise ValueError(
            f"Invalid record duration '{val}'. Use HH:MM:SS, MM:SS, seconds (e.g. '300'), or shorthand (e.g. '5m', '1h30m')."
        )
    return seconds


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

    IGNORED_WARNING_PATTERNS = (
        "ssap (server-side ads) experiment",
        "sabr-only streaming experiment",
        "missing required visitor data",
        "android client https formats require a gvs po token",
        "no gvs po token provided",
        "this client will be deprioritized",
        "some web client https formats have been skipped",
        "some ios client https formats have been skipped",
        "formats have been skipped as they are missing a url",
        "unavailable video is hidden",
        "unavailable videos are hidden",
        "general metadata extraction failed",
        "unable to extract shared data",
        "unable to extract additional data",
        "main webpage is locked behind the login page",
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def debug(self, message: str) -> None:
        if self.config.debug:
            LOGGER.debug(clean_error_message(message))

    def info(self, message: str) -> None:
        if self.config.verbose:
            LOGGER.info(clean_error_message(message))

    def warning(self, message: str) -> None:
        cleaned = clean_error_message(message)
        lowered = cleaned.lower()
        if any(pattern in lowered for pattern in self.IGNORED_WARNING_PATTERNS):
            LOGGER.debug(cleaned)
            return
        LOGGER.warning(cleaned)

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

        try:
            import certifi
            ca_file = certifi.where()
            if Path(ca_file).is_file():
                options["ca_certificates_file"] = ca_file
        except Exception:
            pass

        if self.config.no_check_certificate:
            options["nocheckcertificate"] = True

        js_runtimes = discover_js_runtimes()
        if js_runtimes:
            options["js_runtimes"] = js_runtimes

        ffmpeg_bin = find_ffmpeg()
        if ffmpeg_bin:
            options["ffmpeg_location"] = str(ffmpeg_bin.parent)

        # Let yt-dlp use its native default YouTube client selection & PO-token format filtering
        # (avoids deprecated 'tv_embedded' warnings and 'missing_pot' HTTP 403 Forbidden failures).
        # Fallback client rotation is handled in platform_extra_options() on retry attempts.

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

        if self.config.concurrent_fragments:
            options["concurrent_fragment_downloads"] = max(1, self.config.concurrent_fragments)

        if getattr(self.config, "aria2", False):
            aria2_bin = shutil.which("aria2c")
            if aria2_bin or Path("aria2c.exe").is_file():
                options["external_downloader"] = {"default": "aria2c"}
                options["external_downloader_args"] = {
                    "aria2c": [
                        "-j", str(max(4, self.config.concurrent_fragments * 2)),
                        "-s", "16",
                        "-x", "16",
                        "-k", "1M",
                        "--min-split-size=1M",
                        "--summary-interval=0",
                    ]
                }
            else:
                LOGGER.debug("aria2c requested but executable not found on PATH; falling back to built-in multi-connection engine")

        min_fs = parse_rate_limit(self.config.min_filesize)
        if min_fs:
            options["min_filesize"] = min_fs

        max_fs = parse_rate_limit(self.config.max_filesize)
        if max_fs:
            options["max_filesize"] = max_fs

        return options

    def platform_extra_options(
        self,
        platform: Platform,
        attempt: int = 1,
    ) -> dict[str, Any]:
        if platform in (Platform.TIKTOK, Platform.INSTAGRAM):
            return {
                "extractor_retries": 2,
            }
        if platform == Platform.YOUTUBE:
            # Attempt 1 uses yt-dlp's native default clients & PO-token filtering (no missing_pot)
            # to avoid HTTP 403 Forbidden on PO-token-gated DASH formats and deprecated client warnings.
            if attempt <= 1:
                return {}

            has_auth = bool(self.config.cookies_file or self.config.cookies_from_browser)
            if attempt == 2:
                clients = (
                    ["tv_downgraded", "web_safari", "web_embedded", "web"]
                    if has_auth
                    else ["tv_simply", "tv", "web_safari", "web"]
                )
            elif attempt == 3:
                clients = (
                    ["mweb", "tv", "web"]
                    if has_auth
                    else ["web_embedded", "mweb", "ios", "web"]
                )
            else:
                clients = (
                    ["web_creator", "web"]
                    if has_auth
                    else ["android_vr", "android", "web"]
                )

            return {
                "extractor_args": {
                    "youtube": {
                        "player_client": clients,
                    }
                }
            }
        return {}

    def extract_info(
        self,
        url: str,
        download: bool = False,
        extra: Optional[dict[str, Any]] = None,
        platform: Platform = Platform.UNKNOWN,
    ) -> dict[str, Any]:
        options = self.base_options()
        options.update(self.platform_extra_options(platform))
        if extra:
            options.update(extra)

        LOGGER.debug("Extracting URL: %s", url)

        try:
            with self.yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)

            if not isinstance(info, dict):
                raise ExtractionError("The extractor returned no usable metadata.")

            return info

        except ExtractionError:
            raise
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
        attempt: int = 1,
        is_playlist: bool = False,
    ) -> dict[str, Any]:
        options = self.base_options()
        options.update(self.platform_extra_options(platform, attempt=attempt))

        postprocessors: list[dict[str, Any]] = []

        options.update(
            {
                "format": format_selector,
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "retries": 0,
                "fragment_retries": 0,
                # On playlists, skip deleted/private/unavailable videos instead of aborting the whole playlist
                "ignoreerrors": "only_download" if is_playlist else False,
                "writethumbnail": self.config.write_thumbnail or self.config.embed_thumbnail,
                "writeinfojson": False,
            }
        )

        # Time range / Section slicing
        range_start: Optional[float] = None
        range_end: Optional[float] = None

        if self.config.download_sections:
            sec_spec = self.config.download_sections.strip().lstrip("*")
            if "-" in sec_spec:
                s_part, e_part = sec_spec.split("-", 1)
                range_start = parse_timestamp_seconds(s_part) or 0.0
                range_end = parse_timestamp_seconds(e_part)
            else:
                range_start = parse_timestamp_seconds(sec_spec) or 0.0

        if self.config.start_time is not None:
            range_start = parse_timestamp_seconds(self.config.start_time) or 0.0

        if self.config.end_time is not None:
            range_end = parse_timestamp_seconds(self.config.end_time)

        if range_start is not None or range_end is not None:
            from yt_dlp.utils import download_range_func
            start_val = range_start or 0.0
            options["download_ranges"] = download_range_func(None, [(start_val, range_end)])
            options["force_keyframes_at_cuts"] = True

        # Live stream recording duration cap
        if getattr(self.config, "live_from_start", False):
            options["live_from_start"] = True

        if getattr(self.config, "record_duration", None):
            cap_seconds = parse_duration_seconds(self.config.record_duration)
            if cap_seconds is not None:
                duration_str = str(int(cap_seconds)) if cap_seconds.is_integer() else f"{cap_seconds:.2f}"
                options["hls_use_mpegts"] = True
                options["external_downloader"] = "ffmpeg"
                ext_args = dict(options.get("external_downloader_args") or {})
                ffmpeg_out_args = list(ext_args.get("ffmpeg") or [])
                ffmpeg_out_args.extend(["-t", duration_str])
                ext_args["ffmpeg"] = ffmpeg_out_args
                options["external_downloader_args"] = ext_args

        wants_audio = (
            self.config.audio_only
            or self.config.quality.strip().lower() in {"audio", "audio-only"}
        )

        # Auto-detect or transparently bootstrap FFmpeg if missing
        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin:
            ffmpeg_bin = ensure_ffmpeg(auto_download=True)

        has_ffmpeg = ffmpeg_bin is not None
        if has_ffmpeg:
            options["ffmpeg_location"] = str(ffmpeg_bin.parent)

        if wants_audio:
            options["format"] = "bestaudio/best"
            if has_ffmpeg:
                if self.config.audio_format != "best":
                    postprocessors.append(
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": self.config.audio_format,
                            "preferredquality": self.config.audio_quality,
                        }
                    )
            else:
                LOGGER.info("FFmpeg not detected; saving original audio stream in native format.")

        elif "+" in format_selector:
            if has_ffmpeg:
                options["format"] = format_selector
            else:
                LOGGER.info("FFmpeg not detected; downloading best pre-merged video+audio stream.")
                options["format"] = "best[acodec!=none][vcodec!=none]/best"

        # EBU R128 (-14 LUFS) audio loudness normalization
        if getattr(self.config, "normalize_audio", False) and has_ffmpeg:
            pp_args = dict(options.get("postprocessor_args") or {})
            ff_args = list(pp_args.get("ffmpeg") or [])
            ff_args.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"])
            pp_args["ffmpeg"] = ff_args
            options["postprocessor_args"] = pp_args

        # Metadata embedding
        if self.config.embed_metadata:
            if has_ffmpeg:
                postprocessors.append(
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                        "add_chapters": True,
                    }
                )
            else:
                LOGGER.info("FFmpeg not detected; preserving metadata as companion JSON file.")
                self.config.no_metadata = False

        # Thumbnail embedding
        if self.config.embed_thumbnail:
            if has_ffmpeg:
                postprocessors.append(
                    {
                        "key": "EmbedThumbnail",
                        "already_have_thumbnail": False,
                    }
                )
            else:
                LOGGER.info("FFmpeg not detected; saving standalone thumbnail image.")
                options["writethumbnail"] = True

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
                if has_ffmpeg:
                    postprocessors.append(
                        {
                            "key": "FFmpegEmbedSubtitle",
                        }
                    )
                else:
                    LOGGER.info("FFmpeg not detected; saving external subtitle file.")
                    options["writesubtitles"] = True

        # Video remuxing
        if self.config.remux_video and not wants_audio:
            if has_ffmpeg:
                postprocessors.append(
                    {
                        "key": "FFmpegVideoRemuxer",
                        "preferedformat": self.config.remux_video,
                    }
                )
            else:
                LOGGER.info("FFmpeg not detected; preserving original container format.")

        # Chapter splitting
        if self.config.split_chapters:
            if has_ffmpeg:
                postprocessors.append(
                    {
                        "key": "FFmpegSplitChapters",
                    }
                )
            else:
                LOGGER.info("FFmpeg not detected; skipping chapter splitting.")

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
