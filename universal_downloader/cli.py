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
from universal_downloader.history import clear_history, get_db_path, get_history
from universal_downloader.logging_utils import configure_logging, format_download_error
from universal_downloader.models import DetectedTarget
from universal_downloader.notify import send_notification
from universal_downloader.profile import USERNAME_PLATFORM_PREFIXES
from universal_downloader.protocol import clean_protocol_url, register_protocol, unregister_protocol
from universal_downloader.updater import update_ytdlp
from universal_downloader.utils.net import detect_target
from universal_downloader.watcher import watch_clipboard


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
    meta_group.add_argument(
        "--write-thumbnail",
        action="store_true",
        help="Save raw thumbnail image file alongside media.",
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
        "--prefer-codec",
        choices=["h264", "vp9", "av01", "hevc"],
        help="Preferred video codec (e.g. h264 for maximum hardware acceleration compatibility).",
    )
    post_group.add_argument(
        "--download-sections",
        metavar="RANGE",
        help="Download specific time range (e.g. '*00:01:30-00:03:00' or '90-180').",
    )
    post_group.add_argument(
        "--start-time",
        help="Start time slice for video download (e.g. '00:01:30').",
    )
    post_group.add_argument(
        "--end-time",
        help="End time slice for video download (e.g. '00:03:15').",
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

    # Output & Paths
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
        "--concurrent-fragments",
        type=int,
        default=None,
        help="Number of concurrent fragments for DASH/HLS streams (speeds up downloads). Default: 4.",
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
        "--min-filesize",
        help="Minimum file size to download (e.g. 5M, 100K).",
    )
    net_group.add_argument(
        "--max-filesize",
        help="Maximum file size to download (e.g. 500M, 2G).",
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

    # History & Database
    hist_group = parser.add_argument_group("History Database")
    hist_group.add_argument(
        "--history",
        nargs="?",
        const=20,
        type=int,
        metavar="N",
        help="List recent downloads from the SQLite history database.",
    )
    hist_group.add_argument(
        "--history-search",
        metavar="QUERY",
        help="Search download history database by title, uploader, or URL.",
    )
    hist_group.add_argument(
        "--history-clear",
        action="store_true",
        help="Clear all records from the download history database.",
    )
    hist_group.add_argument(
        "--no-history",
        action="store_true",
        help="Do not save download records to the SQLite history database.",
    )

    # Automation, Watcher & OS Integration
    integ_group = parser.add_argument_group("Automation & System Integration")
    integ_group.add_argument(
        "--notify",
        action="store_true",
        help="Send a native desktop notification upon download completion.",
    )
    integ_group.add_argument(
        "--watch-clipboard",
        action="store_true",
        help="Run clipboard monitor daemon to automatically download copied media URLs.",
    )
    integ_group.add_argument(
        "--watch-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds for clipboard watcher. Default: 1.0.",
    )
    integ_group.add_argument(
        "--register-protocol",
        action="store_true",
        help="Register downloader:// URI scheme in Windows Registry for browser bookmarklet integration.",
    )
    integ_group.add_argument(
        "--unregister-protocol",
        action="store_true",
        help="Remove downloader:// URI scheme from Windows Registry.",
    )
    integ_group.add_argument(
        "--update",
        action="store_true",
        help="Check and upgrade yt-dlp to the latest PyPI release.",
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
        "--json-stream",
        action="store_true",
        dest="json_stream",
        help="Stream real-time line-delimited JSON events to stdout for C#/external GUI integration.",
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
            value = clean_protocol_url(value)

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

    # Self-updater
    if getattr(args, "update", False):
        ok, msg = update_ytdlp()
        if args.json_output:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            if ok:
                success(msg, build_config(args))
            else:
                failure(msg, build_config(args))
        return 0 if ok else 1

    # Custom Windows Protocol Handlers (downloader://)
    if getattr(args, "register_protocol", False):
        ok, msg = register_protocol()
        if args.json_output:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            if ok:
                success(msg, build_config(args))
            else:
                failure(msg, build_config(args))
        return 0 if ok else 1

    if getattr(args, "unregister_protocol", False):
        ok, msg = unregister_protocol()
        if args.json_output:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            if ok:
                success(msg, build_config(args))
            else:
                failure(msg, build_config(args))
        return 0 if ok else 1

    target: Optional[DetectedTarget] = None

    try:
        config = build_config(args)
        configure_logging(config)
        engine = DownloadEngine(config)

        # History database operations
        db_path = get_db_path(config.output_dir)

        if getattr(args, "history_clear", False):
            deleted = clear_history(db_path)
            if config.json_output:
                print(json.dumps({"success": True, "deleted_count": deleted}))
            else:
                success(f"Cleared {deleted} history records.", config)
            return 0

        if getattr(args, "history", None) is not None or getattr(args, "history_search", None):
            limit = args.history if args.history is not None else 50
            search = getattr(args, "history_search", None)
            records = get_history(db_path, limit=limit, search=search)

            if config.json_output:
                print(json.dumps(records, indent=2))
            else:
                print_banner(config)
                if not records:
                    info("No download history found.", config)
                else:
                    print(f"{'ID':<6} {'DATE':<20} {'PLATFORM':<12} {'TITLE':<45} {'STATUS':<10}")
                    print("-" * 95)
                    for r in records:
                        date_str = (r.get("downloaded_at") or "")[:19]
                        title_str = (r.get("title") or "")[:42]
                        print(f"{r['id']:<6} {date_str:<20} {r.get('platform', ''):<12.12} {title_str:<45} {r.get('status', ''):<10}")
                    print("-" * 95)
            return 0

        # Clipboard Watcher Daemon
        if getattr(args, "watch_clipboard", False):
            watch_clipboard(engine, interval=config.watch_interval)
            return 0

        requested_url = validate_url_option(args)
        if requested_url:
            requested_url = clean_protocol_url(requested_url)

        # Formats inspection mode
        if args.formats:
            fmt_url = clean_protocol_url(args.formats)
            target = detect_target(fmt_url, timeout=config.timeout)

            if not config.json_output and not config.json_stream:
                print_banner(config)
                print(f"URL:      {target.normalized_url}")
                print(f"Platform: {target.platform.value}")
                print()

            info_data = engine.inspect(
                target.normalized_url,
                platform=target.platform,
            )

            if config.json_output or config.json_stream:
                formats_data = [fmt.raw for fmt in parse_format(info_data)]
                print(json.dumps({"url": target.normalized_url, "formats": formats_data}, indent=2))
            else:
                print(f"Title: {info_data.get('title') or 'unknown'}")
                print_formats(info_data, config)

            return 0

        # Profile picture resolution mode
        if args.profile:
            prof_val = clean_protocol_url(args.profile)
            if not config.json_output and not config.json_stream:
                print_banner(config)

            saved = engine.download_profile(prof_val)

            if config.json_output or config.json_stream:
                print(json.dumps({"success": True, "saved_profile": str(saved)}))
            else:
                success(f"Profile picture saved: {saved}", config)

            return 0

        # Batch mode
        if args.batch:
            urls = read_batch_file(args.batch)

            if not urls:
                if not config.json_output and not config.json_stream:
                    warning("The batch file contains no URLs.", config)
                else:
                    print(json.dumps({"successful": 0, "failed": 0, "skipped": 0, "failures": []}))
                return 0

            if not config.json_output and not config.json_stream:
                print_banner(config)

            summary = run_batch(engine, urls)

            if config.notify:
                send_notification(
                    "Batch Downloads Finished",
                    f"Completed: {summary.successful}, Failed: {summary.failed}",
                )

            if config.json_output or config.json_stream:
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
            if not config.json_output and not config.json_stream:
                print_banner(config)

            try:
                target = detect_target(requested_url, timeout=config.timeout)

                if not config.json_output and not config.json_stream:
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
                elif not config.json_stream:
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

                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": formatted_err}))
                else:
                    failure(f"Download failed\n\nReason:\n{formatted_err}", config)

                return 1

            except Exception as exc:
                if config.json_output or config.json_stream:
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
