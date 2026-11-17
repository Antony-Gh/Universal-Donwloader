"""Command line interface, argument parser, interactive shell, and program entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from universal_downloader import __app_name__, __version__
from universal_downloader.batch import print_batch_summary, read_batch_file, run_batch
from universal_downloader.config import build_config, generate_default_config
from universal_downloader.console import failure, info, print_banner, success, warning
from universal_downloader.engine import DownloadEngine
from universal_downloader.exceptions import (
    ConfigurationError,
    DependencyError,
    DownloadError,
    ExtractionError,
    ProfileError,
    UnsupportedPlatformError,
)
from universal_downloader.formats import parse_format, print_formats, unique_video_heights
from universal_downloader.logging_utils import configure_logging, format_download_error
from universal_downloader.models import DetectedTarget
from universal_downloader.profile import USERNAME_PLATFORM_PREFIXES
from universal_downloader.utils.net import detect_target


def platform_python_version() -> str:
    return sys.version.split()[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="downloader.py",
        description=(
            "Universal Media Downloader for publicly accessible media "
            "that the user is authorized to download."
        ),
        epilog=(
            "This application operates on public resources and does not bypass "
            "CAPTCHAs, DRM, private profiles, or unauthorized technical barriers."
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
        help="Read URLs from a text file (one URL per line).",
    )

    parser.add_argument(
        "--profile",
        help=(
            "Download a publicly exposed profile image from a public "
            "profile URL or platform:username (e.g. instagram:username)."
        ),
    )

    parser.add_argument(
        "--formats",
        metavar="URL",
        help="List formats available for a URL without downloading.",
    )

    # Audio options
    audio_group = parser.add_argument_group("Audio Options")
    audio_group.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio stream.",
    )
    audio_group.add_argument(
        "--audio-format",
        choices=["best", "mp3", "m4a", "flac", "opus", "wav", "aac"],
        default=None,
        help="Audio format when extracting audio. Default: mp3 (or 'best' to keep original).",
    )
    audio_group.add_argument(
        "--audio-quality",
        default=None,
        help="Audio quality (e.g. 192k, 320k, or 0 for best VBR). Default: 192k.",
    )

    # Metadata & Artwork
    meta_group = parser.add_argument_group("Metadata & Artwork")
    meta_group.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not save .json metadata alongside downloads.",
    )
    meta_group.add_argument(
        "--embed-metadata",
        action="store_true",
        help="Embed metadata tags (title, artist, date, chapters) into media container.",
    )
    meta_group.add_argument(
        "--embed-thumbnail",
        action="store_true",
        help="Embed thumbnail / cover artwork directly into media file.",
    )

    # Subtitles
    sub_group = parser.add_argument_group("Subtitles")
    sub_group.add_argument(
        "--write-subs",
        action="store_true",
        help="Write subtitle file to disk alongside media.",
    )
    sub_group.add_argument(
        "--embed-subs",
        action="store_true",
        help="Embed subtitles directly into video container (requires FFmpeg).",
    )
    sub_group.add_argument(
        "--sub-langs",
        help="Comma-separated language codes for subtitles (e.g. 'en,es' or 'all').",
    )
    sub_group.add_argument(
        "--auto-subs",
        action="store_true",
        help="Include automatically generated speech-to-text subtitles if available.",
    )

    # Video & Postprocessing
    post_group = parser.add_argument_group("Video & Postprocessing")
    post_group.add_argument(
        "--quality",
        default=None,
        help=(
            "Video quality: best, 2160p, 1440p, 1080p, 720p, 480p, "
            "audio, or explicit yt-dlp selector string."
        ),
    )
    post_group.add_argument(
        "--remux-video",
        choices=["mp4", "mkv", "mov", "webm"],
        help="Remux downloaded video into chosen container format.",
    )
    post_group.add_argument(
        "--split-chapters",
        action="store_true",
        help="Split video into multiple files based on internal chapters.",
    )
    post_group.add_argument(
        "--sponsorblock-remove",
        metavar="CATEGORIES",
        help="Remove segments via SponsorBlock (e.g. 'sponsor,intro,outro').",
    )

    # Output & Organization
    out_group = parser.add_argument_group("Output & Paths")
    out_group.add_argument(
        "--output",
        help="Base output directory. Default: downloads",
    )
    out_group.add_argument(
        "--output-template",
        help="Custom yt-dlp naming template (e.g. '%%(uploader)s - %%(title)s.%%(ext)s').",
    )
    out_group.add_argument(
        "--download-archive",
        type=Path,
        help="Track and skip previously downloaded files using an archive text file.",
    )

    # Playlists
    pl_group = parser.add_argument_group("Playlists")
    pl_group.add_argument(
        "--playlist-items",
        help="Playlist item indices to download (e.g. '1,2,5-8').",
    )
    pl_group.add_argument(
        "--max-downloads",
        type=int,
        help="Maximum number of media items to download from a playlist/feed.",
    )

    # Performance & Networking
    net_group = parser.add_argument_group("Networking & Performance")
    net_group.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Number of concurrent downloads in batch mode (1 to 16). Default: 1.",
    )
    net_group.add_argument(
        "--retries",
        type=int,
        default=None,
        help="Number of retries for transient network failures. Default: 3.",
    )
    net_group.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Network timeout in seconds. Default: 30.",
    )
    net_group.add_argument(
        "--limit-rate",
        help="Maximum download bandwidth (e.g. 5M, 500K).",
    )
    net_group.add_argument(
        "--sleep-interval",
        type=int,
        default=None,
        help="Seconds to sleep between batch downloads for polite scraping.",
    )
    net_group.add_argument(
        "--max-sleep-interval",
        type=int,
        default=None,
        help="Upper bound for random sleep jitter between batch downloads.",
    )
    net_group.add_argument(
        "--proxy",
        help="HTTP/HTTPS/SOCKS5 proxy URL (e.g. socks5://127.0.0.1:1080).",
    )
    net_group.add_argument(
        "--geo-bypass",
        action="store_true",
        help="Attempt to bypass geographic restrictions via header spoofing.",
    )

    # Authentication & Cookies
    auth_group = parser.add_argument_group("Authentication & Cookies")
    auth_group.add_argument(
        "--cookies",
        type=Path,
        help="Netscape-format cookies file for authenticated requests.",
    )
    auth_group.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER[:PROFILE]",
        help="Load cookies from browser profile (e.g. chrome, edge, firefox).",
    )

    # Developer & CLI experience
    dev_group = parser.add_argument_group("Developer & Utility")
    dev_group.add_argument(
        "--dry-run",
        "--simulate",
        action="store_true",
        dest="dry_run",
        help="Simulate download and display metadata without saving files to disk.",
    )
    dev_group.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured JSON results to stdout for programmatic integration.",
    )
    dev_group.add_argument(
        "--init-config",
        action="store_true",
        help="Generate starter config.json and .env files with sensible defaults.",
    )
    dev_group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable informational logging.",
    )
    dev_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable full debug logging.",
    )
    dev_group.add_argument(
        "--no-color",
        action="store_true",
        help="Disable terminal colors.",
    )
    dev_group.add_argument(
        "--version",
        action="version",
        version=(
            f"{__app_name__}\n"
            f"Version: {__version__}\n"
            f"Python: {platform_python_version()}"
        ),
    )

    return parser


def validate_url_option(args: argparse.Namespace) -> Optional[str]:
    if args.url and args.url_option:
        raise ConfigurationError("Specify either a positional URL or --url, not both.")
    return args.url or args.url_option


def interactive_mode(engine: DownloadEngine) -> int:
    config = engine.config
    print_banner(config)

    while True:
        try:
            value = input(
                "Enter URL, profile URL, platform:username, or 'q' to quit:\n> "
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
                prefix = value.split(":", 1)[0].lower()
                if prefix in USERNAME_PLATFORM_PREFIXES:
                    saved = engine.download_profile(value)
                    success(f"Profile picture saved: {saved}", config)
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
                warning(f"Could not inspect formats: {exc}", config)
                info_data = {}

            if info_data:
                formats = parse_format(info_data)
                heights = unique_video_heights(formats)

                if heights:
                    print()
                    print("Available qualities:")
                    print("1. Best")
                    for number, height in enumerate(heights[:8], start=2):
                        print(f"{number}. {height}p")
                    print(f"{len(heights) + 2}. Audio only")

                    selection = input("Select [1]: ").strip()

                    if not selection or selection == "1":
                        config.quality = "best"
                        config.audio_only = False
                    elif selection == str(len(heights) + 2):
                        config.audio_only = True
                        config.quality = "audio"
                    else:
                        try:
                            selected_index = int(selection) - 2
                            if 0 <= selected_index < len(heights):
                                config.quality = f"{heights[selected_index]}p"
                                config.audio_only = False
                            else:
                                config.quality = "best"
                                config.audio_only = False
                        except ValueError:
                            config.quality = "best"
                            config.audio_only = False

            result = engine.download(target.normalized_url)
            success("Download completed.", config)
            for path in result.files:
                print(f"Saved: {path}")

        except Exception as exc:
            failure(str(exc), config)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Starter config generation
    if getattr(args, "init_config", False):
        json_f, env_f = generate_default_config(Path.cwd())
        print(f"✓ Configuration templates generated:\n  • {json_f}\n  • {env_f}")
        return 0

    target: Optional[DetectedTarget] = None

    try:
        config = build_config(args)
        configure_logging(config)
        engine = DownloadEngine(config)

        requested_url = validate_url_option(args)

        # Formats inspection mode
        if args.formats:
            target = detect_target(args.formats, timeout=config.timeout)

            if not config.json_output:
                print_banner(config)
                print(f"URL:      {target.normalized_url}")
                print(f"Platform: {target.platform.value}")
                print()

            info_data = engine.inspect(
                target.normalized_url,
                platform=target.platform,
            )

            if config.json_output:
                formats_data = [fmt.raw for fmt in parse_format(info_data)]
                print(json.dumps({"url": target.normalized_url, "formats": formats_data}, indent=2))
            else:
                print(f"Title: {info_data.get('title') or 'unknown'}")
                print_formats(info_data, config)

            return 0

        # Profile picture resolution mode
        if args.profile:
            if not config.json_output:
                print_banner(config)

            saved = engine.download_profile(args.profile)

            if config.json_output:
                print(json.dumps({"success": True, "saved_profile": str(saved)}))
            else:
                success(f"Profile picture saved: {saved}", config)

            return 0

        # Batch mode
        if args.batch:
            urls = read_batch_file(args.batch)

            if not urls:
                if not config.json_output:
                    warning("The batch file contains no URLs.", config)
                else:
                    print(json.dumps({"successful": 0, "failed": 0, "skipped": 0, "failures": []}))
                return 0

            if not config.json_output:
                print_banner(config)

            summary = run_batch(engine, urls)

            if config.json_output:
                print(
                    json.dumps(
                        {
                            "successful": summary.successful,
                            "failed": summary.failed,
                            "skipped": summary.skipped,
                            "failures": summary.failures,
                        },
                        indent=2,
                    )
                )
            else:
                print_batch_summary(summary, config)

            return 1 if summary.failed else 0

        # Single URL execution
        if requested_url:
            if not config.json_output:
                print_banner(config)

            try:
                target = detect_target(requested_url, timeout=config.timeout)

                if not config.json_output:
                    print(f"URL:      {target.normalized_url}")
                    print(f"Platform: {target.platform.value}")
                    print(f"Type:     {target.content_type.value}")
                    print()
                    info("Processing...", config)

                result = engine.download(target.normalized_url)

                if config.json_output:
                    print(
                        json.dumps(
                            {
                                "success": result.success,
                                "url": result.url,
                                "files": [str(p) for p in result.files],
                                "dry_run": config.dry_run,
                            },
                            indent=2,
                        )
                    )
                else:
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
                platform_arg = target.platform if target else None
                formatted_err = format_download_error(exc, platform_arg)

                if config.json_output:
                    print(json.dumps({"success": False, "error": formatted_err}))
                else:
                    failure(f"Download failed\n\nReason:\n{formatted_err}", config)

                return 1

            except Exception as exc:
                if config.json_output:
                    print(json.dumps({"success": False, "error": str(exc)}))
                else:
                    failure(f"Download failed\n\nReason:\n{exc}", config)

                return 1

        # Interactive Mode
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
        print(f"✗ Unexpected application error\n\n{exc}", file=sys.stderr)
        return 1
