#!/usr/bin/env python3
"""
Universal Media Downloader
Production-grade command-line downloader for publicly accessible media.

This file serves as both an executable entry point and backward-compatible module.
Core implementation has been structured into the `universal_downloader` package.
"""

from __future__ import annotations

import sys

from universal_downloader import __app_name__ as APP_NAME, __version__ as APP_VERSION
from universal_downloader.batch import print_batch_summary, read_batch_file, run_batch
from universal_downloader.cli import (
    build_parser,
    interactive_mode,
    main,
    platform_python_version,
    validate_url_option,
)
from universal_downloader.config import (
    build_config,
    env_value,
    load_json_config,
    parse_config_int,
    parse_dotenv,
)
from universal_downloader.console import (
    ctext,
    failure,
    info,
    print_banner,
    success,
    supports_color,
    warning,
)
from universal_downloader.engine import DownloadEngine
from universal_downloader.exceptions import (
    ConfigurationError,
    DependencyError,
    DownloaderError,
    DownloadError,
    ExtractionError,
    ProfileError,
    UnsupportedPlatformError,
)
from universal_downloader.extractor import (
    YTDLPExtractor,
    YTDLPLogger,
    check_ffmpeg,
    check_ffprobe,
    discover_js_runtimes,
    import_yt_dlp,
)
from universal_downloader.formats import (
    format_sort_key,
    parse_format,
    print_formats,
    quality_to_selector,
    unique_video_heights,
)
from universal_downloader.logging_utils import (
    ANSI_ESCAPE_RE,
    LOGGER,
    TIKTOK_INTERNAL_RETRIES,
    TIKTOK_RETRY_DELAYS,
    SecretFilter,
    clean_error_message,
    configure_logging,
    format_download_error,
    is_non_retryable_error,
    is_tiktok_rehydration_error,
)
from universal_downloader.models import (
    AppConfig,
    BatchSummary,
    ContentType,
    DetectedTarget,
    DownloadResult,
    FormatInfo,
    Platform,
)
from universal_downloader.profile import (
    USERNAME_PLATFORM_PREFIXES,
    ProfilePhotoResolver,
    download_public_image,
    extract_meta_image,
    extract_thumbnail_candidates,
    extract_username_from_profile_url,
    fetch_public_html,
    image_extension_from_url,
    resolve_profile_input,
)
from universal_downloader.progress import (
    ProgressRenderer,
    human_eta,
    human_size,
    human_speed,
)
from universal_downloader.utils.fs import (
    INVALID_FILENAME_CHARS,
    WINDOWS_RESERVED_NAMES,
    compact_metadata,
    ensure_inside_directory,
    platform_directory,
    preferred_media_filename,
    rename_media_file,
    safe_json_value,
    sanitize_filename,
    unique_path,
    write_metadata_file,
)
from universal_downloader.utils.net import (
    PLATFORM_DOMAINS,
    TIKTOK_SHORT_DOMAINS,
    TIKTOK_VIDEO_PATH_RE,
    detect_content_type,
    detect_platform,
    detect_target,
    domain_matches,
    get_domain,
    normalize_tiktok_url,
    normalize_url,
    resolve_url_redirect,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ANSI_ESCAPE_RE",
    "PLATFORM_DOMAINS",
    "TIKTOK_SHORT_DOMAINS",
    "TIKTOK_VIDEO_PATH_RE",
    "TIKTOK_INTERNAL_RETRIES",
    "TIKTOK_RETRY_DELAYS",
    "INVALID_FILENAME_CHARS",
    "WINDOWS_RESERVED_NAMES",
    "USERNAME_PLATFORM_PREFIXES",
    "LOGGER",
    "DownloaderError",
    "ConfigurationError",
    "DependencyError",
    "UnsupportedPlatformError",
    "ExtractionError",
    "DownloadError",
    "ProfileError",
    "Platform",
    "ContentType",
    "AppConfig",
    "DetectedTarget",
    "FormatInfo",
    "DownloadResult",
    "BatchSummary",
    "SecretFilter",
    "ProgressRenderer",
    "YTDLPLogger",
    "YTDLPExtractor",
    "ProfilePhotoResolver",
    "DownloadEngine",
    "configure_logging",
    "clean_error_message",
    "format_download_error",
    "is_tiktok_rehydration_error",
    "is_non_retryable_error",
    "supports_color",
    "ctext",
    "success",
    "failure",
    "info",
    "warning",
    "print_banner",
    "import_yt_dlp",
    "check_ffmpeg",
    "check_ffprobe",
    "discover_js_runtimes",
    "parse_dotenv",
    "load_json_config",
    "env_value",
    "parse_config_int",
    "build_config",
    "normalize_url",
    "get_domain",
    "resolve_url_redirect",
    "normalize_tiktok_url",
    "domain_matches",
    "detect_platform",
    "detect_content_type",
    "detect_target",
    "sanitize_filename",
    "preferred_media_filename",
    "rename_media_file",
    "ensure_inside_directory",
    "unique_path",
    "platform_directory",
    "human_size",
    "human_speed",
    "human_eta",
    "safe_json_value",
    "compact_metadata",
    "write_metadata_file",
    "parse_format",
    "format_sort_key",
    "unique_video_heights",
    "print_formats",
    "quality_to_selector",
    "extract_meta_image",
    "fetch_public_html",
    "extract_thumbnail_candidates",
    "image_extension_from_url",
    "download_public_image",
    "extract_username_from_profile_url",
    "resolve_profile_input",
    "read_batch_file",
    "run_batch",
    "print_batch_summary",
    "interactive_mode",
    "build_parser",
    "platform_python_version",
    "validate_url_option",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
