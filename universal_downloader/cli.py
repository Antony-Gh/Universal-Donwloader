"""Command line interface, argument parser, interactive shell, and program entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from universal_downloader import __app_name__, __version__
from universal_downloader.batch import print_batch_summary, read_batch_file, run_batch
from universal_downloader.config import build_config, generate_default_config
from universal_downloader.console import failure, info, print_banner, success, warning
from universal_downloader.converter import (
    AUDIO_FORMATS,
    SUPPORTED_FORMATS,
    VIDEO_FORMATS,
    convert_media_file,
    create_clip,
    extract_frame,
    video_to_gif,
)
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
from universal_downloader.models import ContentType, DetectedTarget, Platform
from universal_downloader.notify import send_notification
from universal_downloader.profile import (
    USERNAME_PLATFORM_PREFIXES,
    download_direct_profile_image,
    extract_username_from_profile_url,
    inspect_profile_images_detailed,
    resolve_profile_input,
)
from universal_downloader.native_host import (
    register_native_host,
    run_native_host,
    unregister_native_host,
)
from universal_downloader.protocol import clean_protocol_url, register_protocol, unregister_protocol
from universal_downloader.updater import update_ytdlp
from universal_downloader.search import fetch_suggestions, is_valid_search_query, search_youtube
from universal_downloader.sniffer import sniff_page_media
from universal_downloader.subscriptions import (
    add_subscription,
    list_subscriptions,
    remove_subscription,
    sync_subscriptions,
)
from universal_downloader.telemetry import (
    fetch_github_release_stats,
    fetch_neon_device_stats,
    format_analytics_dashboard,
    send_telemetry_heartbeat,
)
from universal_downloader.utils.net import detect_target
from universal_downloader.version_policy import enforce_version_policy
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
        "--profile-image-url",
        metavar="IMAGE_URL",
        help="Directly download a specific discovered profile or cover image URL.",
    )

    parser.add_argument(
        "--profile-source-url",
        metavar="PROFILE_URL",
        help="Optional originating profile URL used for folder/filename organization with --profile-image-url.",
    )

    parser.add_argument(
        "--enhance-hd",
        action="store_true",
        help="Apply detail-preserving HD upscaling/enhancement when downloading --profile-image-url.",
    )

    parser.add_argument(
        "--formats",
        metavar="URL",
        help="List formats available for a URL without downloading.",
    )

    parser.add_argument(
        "--metadata",
        metavar="URL",
        help="Fetch media metadata and thumbnail without downloading.",
    )

    # Search options
    search_group = parser.add_argument_group("Search & Discovery")
    search_group.add_argument(
        "--search",
        metavar="QUERY",
        help="Search YouTube for videos/songs matching query and output results.",
    )
    search_group.add_argument(
        "--search-limit",
        type=int,
        default=10,
        help="Maximum search results to return (1-25, default: 10).",
    )
    search_group.add_argument(
        "--suggest",
        metavar="QUERY",
        help="Fetch real-time search autosuggestions for a query string.",
    )
    search_group.add_argument(
        "--sniff",
        "--extract-page-media",
        dest="sniff",
        metavar="PAGE_URL",
        help="Scan an arbitrary webpage HTML for embedded video, audio, HLS (.m3u8), and DASH (.mpd) streams.",
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
    audio_group.add_argument(
        "--normalize-audio",
        action="store_true",
        help="Normalize audio loudness to -14 LUFS (EBU R128 streaming standard) via FFmpeg loudnorm filter.",
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
        "--record-duration",
        "--record",
        dest="record_duration",
        metavar="DURATION",
        help="Cap live stream recording duration (e.g. '00:10:00', '300', or '5m') and finalize cleanly with FFmpeg.",
    )
    post_group.add_argument(
        "--live-from-start",
        action="store_true",
        help="Start recording live streams from the beginning when supported by the platform.",
    )
    post_group.add_argument(
        "--remux-video",
        choices=["mp4", "mkv", "mov", "webm"],
        help="Remux downloaded or local video into chosen container format.",
    )
    post_group.add_argument(
        "--convert",
        metavar="FORMAT",
        choices=sorted(SUPPORTED_FORMATS),
        help="Convert a local media file directly using FFmpeg (mp3, m4a, flac, opus, wav, aac, mp4, mkv, mov, webm).",
    )
    post_group.add_argument(
        "--convert-audio",
        metavar="FORMAT",
        choices=sorted(AUDIO_FORMATS),
        help="Extract audio from a local media file into the specified format (mp3, m4a, flac, opus, wav, aac).",
    )
    post_group.add_argument(
        "--convert-video",
        metavar="FORMAT",
        choices=sorted(VIDEO_FORMATS),
        help="Convert a local video file into the specified container format (mp4, mkv, mov, webm).",
    )
    post_group.add_argument(
        "--to-gif",
        action="store_true",
        help="Convert video (local file or downloaded) to high-quality animated GIF.",
    )
    post_group.add_argument(
        "--gif-fps",
        type=int,
        default=15,
        help="Framerate for GIF conversion (default: 15).",
    )
    post_group.add_argument(
        "--gif-width",
        type=int,
        default=480,
        help="Width in pixels for GIF conversion (default: 480).",
    )
    post_group.add_argument(
        "--frame-grab",
        "--screenshot-at",
        metavar="TIMESTAMP",
        dest="frame_grab",
        help="Grab a single frame/screenshot from video at given timestamp (e.g. '00:01:23').",
    )
    post_group.add_argument(
        "--make-clip",
        action="store_true",
        help="Extract a video clip from local file using --start-time and --end-time / --record-duration.",
    )
    post_group.add_argument(
        "--tag-music",
        "--auto-tag",
        action="store_true",
        dest="tag_music",
        help="Enrich audio files with metadata and cover art from MusicBrainz & Cover Art Archive.",
    )
    post_group.add_argument(
        "--share",
        "--serve",
        action="store_true",
        dest="share",
        help="Host media on local network and display QR code to transfer directly to mobile devices.",
    )
    post_group.add_argument(
        "--share-port",
        type=int,
        default=0,
        metavar="PORT",
        help="Local network port to bind for file sharing (default: random available port).",
    )
    post_group.add_argument(
        "--check-duplicates",
        action="store_true",
        help="Check download history and local storage before downloading to avoid duplicates.",
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
    post_group.add_argument(
        "--preset",
        metavar="PRESET",
        help="Device & social optimization preset ('discord', 'discord_10mb', 'whatsapp', 'car_audio', 'tv_theater').",
    )
    post_group.add_argument(
        "--preset-list",
        action="store_true",
        help="List available device and social media optimization presets.",
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
        "--organize",
        "--subfolder-mode",
        dest="organize",
        choices=["none", "platform", "uploader", "date"],
        default=None,
        help="Subfolder routing mode: none (flat), platform (default), uploader (platform/uploader), or date (platform/YYYY-MM).",
    )
    out_group.add_argument(
        "--clean-filenames",
        action="store_true",
        help="Strip clickbait tags (e.g. [Official Video], (Lyrics), 4K) and emojis from downloaded filenames.",
    )
    out_group.add_argument(
        "--verify",
        "--verify-integrity",
        dest="verify_integrity",
        action="store_true",
        help="Verify post-download media container integrity and decodable stream headers via FFmpeg.",
    )
    out_group.add_argument(
        "--write-checksum",
        action="store_true",
        help="Compute SHA-256 digest and write a <file>.sha256 sidecar alongside downloaded media.",
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
    pl_group.add_argument(
        "--subscribe",
        metavar="FEED_URL",
        help="Add a channel or playlist URL to your persistent subscriptions watchlist.",
    )
    pl_group.add_argument(
        "--unsubscribe",
        metavar="URL_OR_ID",
        help="Remove a channel or playlist subscription by URL or numeric ID.",
    )
    pl_group.add_argument(
        "--list-subscriptions",
        "--subscriptions",
        dest="list_subscriptions",
        action="store_true",
        help="List all subscribed channels and playlists.",
    )
    pl_group.add_argument(
        "--sync-subscriptions",
        action="store_true",
        help="Download new uploads from all subscribed channels/playlists using the subscription archive.",
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
    net_group.add_argument(
        "--no-check-certificate",
        action="store_true",
        help="Suppress HTTPS certificate validation (useful behind proxies or missing Windows certs).",
    )
    net_group.add_argument(
        "--aria2",
        action="store_true",
        help="Accelerate downloads using aria2c multi-connection engine (16 parallel segments like IDM).",
    )

    # Smart Scheduling & Power Conditions
    sched_group = parser.add_argument_group("Smart Scheduling & Power Conditions")
    sched_group.add_argument(
        "--schedule",
        type=str,
        default=None,
        metavar="HH:MM",
        help="Schedule download to begin at a specific 24-hour time (e.g. '02:00', '23:30').",
    )
    sched_group.add_argument(
        "--pause-on-battery",
        action="store_true",
        help="Pause or postpone downloads if running on battery below 20% capacity.",
    )
    sched_group.add_argument(
        "--only-wifi",
        action="store_true",
        help="Restrict downloads to unmetered connections.",
    )

    # Local AI Transcription & Whisper
    ai_group = parser.add_argument_group("Local AI Transcription & Whisper")
    ai_group.add_argument(
        "--transcribe",
        action="store_true",
        help="Transcribe audio/video locally with Whisper and export subtitles/text.",
    )
    ai_group.add_argument(
        "--whisper-model",
        type=str,
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: 'base').",
    )
    ai_group.add_argument(
        "--whisper-lang",
        type=str,
        default=None,
        metavar="LANG",
        help="Spoken language code for transcription (e.g. 'en', 'ar', 'es') or 'auto'.",
    )
    ai_group.add_argument(
        "--transcribe-format",
        type=str,
        default="srt,txt,vtt",
        help="Comma-separated subtitle/transcript export formats: srt, vtt, txt (default: 'srt,txt,vtt').",
    )
    ai_group.add_argument(
        "--summarize",
        action="store_true",
        help="Generate an extractive AI summary of the transcript (.summary.txt).",
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
        "--native-host",
        action="store_true",
        help="Run as a Chrome/Edge/Firefox Native Messaging host (stdio JSON companion mode).",
    )
    integ_group.add_argument(
        "--register-native-host",
        action="store_true",
        help="Register Native Messaging host manifests for Chrome, Edge, and Firefox.",
    )
    integ_group.add_argument(
        "--unregister-native-host",
        action="store_true",
        help="Remove Native Messaging host registrations and manifests.",
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
        "--no-telemetry",
        action="store_true",
        help="Disable anonymous installation and device telemetry.",
    )
    dev_group.add_argument(
        "--analytics",
        "--stats",
        action="store_true",
        dest="analytics",
        help="Display aggregated GitHub release download counts and active device statistics.",
    )
    dev_group.add_argument(
        "--release-stats",
        action="store_true",
        help="Display GitHub release asset download counts only.",
    )
    dev_group.add_argument(
        "--friend",
        dest="friend",
        metavar="NAME",
        help="Attach an optional friend or contributor name to device telemetry (e.g. --friend ahmed).",
    )
    dev_group.add_argument(
        "--ref",
        dest="ref",
        metavar="TAG",
        help="Referral tag or friend identifier (equivalent to --friend).",
    )
    dev_group.add_argument(
        "--privacy",
        "--privacy-info",
        action="store_true",
        dest="privacy_info",
        help="Inspect exact telemetry payload sent to Neon and view GDPR transparency guarantees.",
    )
    dev_group.add_argument(
        "--reset-id",
        action="store_true",
        help="Generate a fresh anonymous device UUID, discarding previous identifier.",
    )
    dev_group.add_argument(
        "--gdpr-wipe",
        action="store_true",
        help="Request complete remote erasure of this installation's telemetry from Neon database.",
    )
    dev_group.add_argument(
        "--credits",
        "--about",
        action="store_true",
        dest="credits",
        help="Display creator, contributor, and open-source acknowledgments.",
    )
    dev_group.add_argument(
        "--force-deprecated",
        action="store_true",
        help="Bypass remote version deprecation check and force running older releases.",
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

            # Text search workflow
            if is_valid_search_query(value) and "://" not in value and not value.startswith("www."):
                info(f"Searching YouTube for '{value}'...", config)
                try:
                    search_results = search_youtube(value, limit=5, proxy=config.proxy, timeout=config.timeout)
                except Exception as s_exc:
                    warning(f"Search failed: {s_exc}", config)
                    search_results = []
                if search_results:
                    print()
                    print(f"Search results for '{value}':")
                    for s_idx, s_item in enumerate(search_results, start=1):
                        s_dur = f" ({s_item['duration_string']})" if s_item.get("duration_string") else ""
                        s_up = f" • {s_item['uploader']}" if s_item.get("uploader") else ""
                        print(f"{s_idx}. {s_item['title']}{s_up}{s_dur}")
                    print(f"{len(search_results) + 1}. Cancel search")
                    s_sel = input(f"Select result to download [1-{len(search_results)}] or Enter to cancel: ").strip()
                    if s_sel.isdigit() and 1 <= int(s_sel) <= len(search_results):
                        value = search_results[int(s_sel) - 1]["url"]
                    else:
                        continue
                else:
                    warning(f"No search results found for '{value}'.", config)
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


def _pick_thumbnail(item: dict[str, Any], platform: Platform) -> Optional[str]:
    thumb = item.get("thumbnail")
    if thumb:
        return str(thumb)
    thumbs = item.get("thumbnails")
    if isinstance(thumbs, list):
        valid = [t for t in thumbs if isinstance(t, dict) and t.get("url")]
        if valid:
            return str(valid[-1]["url"])
    video_id = item.get("id")
    if platform == Platform.YOUTUBE and video_id and len(str(video_id)) == 11:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return None


def _extract_supported_qualities(info: dict[str, Any]) -> list[str]:
    formats = parse_format(info)
    if not formats:
        return []
    heights = [h for h in unique_video_heights(formats) if h >= 144]
    qualities = [f"{h}p" for h in heights]
    if any(fmt.has_audio for fmt in formats):
        qualities.append("Audio")
    return qualities


def _extract_supported_codecs(info: dict[str, Any]) -> list[str]:
    formats = parse_format(info)
    if not formats:
        return []
    codecs: list[str] = []
    has_h264 = any("avc" in (fmt.vcodec or "").lower() or "h264" in (fmt.vcodec or "").lower() for fmt in formats)
    has_vp9 = any("vp9" in (fmt.vcodec or "").lower() or "vp09" in (fmt.vcodec or "").lower() for fmt in formats)
    has_av1 = any("av01" in (fmt.vcodec or "").lower() or "av1" in (fmt.vcodec or "").lower() for fmt in formats)
    if has_h264:
        codecs.append("h264")
    if has_vp9:
        codecs.append("vp9")
    if has_av1:
        codecs.append("av01")
    return codecs


def _build_playlist_entries(
    raw_entries: list[dict[str, Any]],
    platform: Platform,
    default_uploader: str,
) -> list[dict[str, Any]]:
    unavailable_titles = {"[private video]", "[deleted video]", "[unavailable video]"}
    result: list[dict[str, Any]] = []
    for entry in raw_entries:
        raw_title = (entry.get("title") or "").strip()
        if raw_title.lower() in unavailable_titles and not entry.get("duration"):
            continue

        video_id = str(entry.get("id") or "").strip()
        entry_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if entry_url and not entry_url.startswith(("http://", "https://")):
            if platform == Platform.YOUTUBE and video_id:
                entry_url = f"https://www.youtube.com/watch?v={video_id}"
        elif not entry_url and platform == Platform.YOUTUBE and video_id:
            entry_url = f"https://www.youtube.com/watch?v={video_id}"

        if not entry_url:
            continue

        idx = len(result) + 1
        result.append(
            {
                "index": idx,
                "id": video_id,
                "url": entry_url,
                "title": raw_title or f"Video #{idx}",
                "uploader": entry.get("uploader") or entry.get("channel") or entry.get("creator") or default_uploader,
                "duration": entry.get("duration"),
                "duration_string": entry.get("duration_string"),
                "thumbnail": _pick_thumbnail(entry, platform),
                "view_count": entry.get("view_count"),
                "qualities": _extract_supported_qualities(entry),
            }
        )
    return result


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Starter config generation
    if getattr(args, "init_config", False):
        try:
            json_f, env_f = generate_default_config(Path.cwd())
            print(f"✓ Configuration templates generated:\n  • {json_f}\n  • {env_f}")
            return 0
        except (PermissionError, OSError) as exc:
            print(f"✗ Failed to generate config templates in current directory: {exc}", file=sys.stderr)
            return 1

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

    # Browser Native Messaging Host (CoApp)
    if getattr(args, "register_native_host", False):
        ok, msg = register_native_host()
        if args.json_output:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            if ok:
                success(msg, build_config(args))
            else:
                failure(msg, build_config(args))
        return 0 if ok else 1

    if getattr(args, "unregister_native_host", False):
        ok, msg = unregister_native_host()
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

        if getattr(args, "native_host", False):
            return run_native_host(config)

        engine = DownloadEngine(config)

        # Dispatch non-blocking anonymous heartbeat in background
        send_telemetry_heartbeat(config=config, async_send=True)

        # Maintainer Analytics & Release Stats
        if getattr(args, "analytics", False) or getattr(args, "release_stats", False):
            gh_stats = fetch_github_release_stats()
            neon_stats = None
            if not getattr(args, "release_stats", False) and config.telemetry_url:
                neon_stats = fetch_neon_device_stats(
                    config.telemetry_url,
                    auth_token=config.telemetry_key,
                )
            if config.json_output or config.json_stream:
                print(
                    json.dumps(
                        {
                            "success": True,
                            "github_releases": gh_stats,
                            "neon_telemetry": neon_stats,
                        },
                        indent=2,
                    )
                )
            else:
                print_banner(config)
                report = format_analytics_dashboard(gh_stats, neon_stats)
                print(report)
            return 0

        # Privacy & Transparency Dashboard
        if getattr(args, "privacy_info", False):
            from universal_downloader.telemetry import format_privacy_report, get_telemetry_transparency_info
            if config.json_output or config.json_stream:
                print(json.dumps(get_telemetry_transparency_info(config), indent=2))
            else:
                print(format_privacy_report(config))
            return 0

        # Reset Anonymous Install ID
        if getattr(args, "reset_id", False):
            from universal_downloader.telemetry import reset_install_id
            new_id = reset_install_id()
            if config.json_output or config.json_stream:
                print(json.dumps({"success": True, "new_install_id": new_id}))
            else:
                success(f"Anonymous install UUID reset: {new_id}", config)
            return 0

        # GDPR Remote Data Wipe
        if getattr(args, "gdpr_wipe", False):
            from universal_downloader.telemetry import request_gdpr_data_wipe
            ok = request_gdpr_data_wipe(config)
            if config.json_output or config.json_stream:
                print(json.dumps({"success": ok}))
            else:
                if ok:
                    success("GDPR erasure request succeeded: Device records removed from database.", config)
                else:
                    failure("GDPR erasure request failed or remote telemetry server not configured.", config)
            return 0 if ok else 1

        # Preset List
        if getattr(args, "preset_list", False):
            from universal_downloader.presets import list_presets
            presets = list_presets()
            if config.json_output or config.json_stream:
                print(json.dumps({"success": True, "presets": presets}, indent=2))
            else:
                print("=" * 70)
                print("Available Device & Social Media Optimization Presets")
                print("=" * 70)
                for p in presets:
                    size_note = f" (Max: {p['max_size_mb']}MB)" if p.get("max_size_mb") else ""
                    print(f"  • {p['id']:<14} : {p['name']}{size_note}")
                    print(f"    {p['description']}")
                print("=" * 70)
                print("Usage: python downloader.py --preset <preset_name> <URL_or_File>")
            return 0

        # Credits & Creator Acknowledgments
        if getattr(args, "credits", False):
            if config.json_output or config.json_stream:
                print(
                    json.dumps(
                        {
                            "app": __app_name__,
                            "version": __version__,
                            "author": "Anthony Gaius",
                            "github": "https://github.com/Antony-Gh",
                            "repository": "https://github.com/Antony-Gh/Universal-Donwloader",
                            "license": "MIT",
                        },
                        indent=2,
                    )
                )
            else:
                print("=" * 70)
                print(f"🚀 {__app_name__} (v{__version__})")
                print("=" * 70)
                print("👤 Creator & Lead Developer: Anthony Gaius (@Antony-Gh)")
                print("🌐 GitHub Profile:           https://github.com/Antony-Gh")
                print("⭐ Project Repository:       https://github.com/Antony-Gh/Universal-Donwloader")
                print("✉️ Contact & Support:        knkmam05@gmail.com")
                print("📄 License:                  MIT License (Open Source)")
                print("-" * 70)
                print("Special thanks to yt-dlp, FFmpeg, Avalonia UI, Jetpack Compose,")
                print("aria2c, Whisper, and the open-source community.")
                print("=" * 70)
            return 0

        # Remote Version Lifecycle & Deprecation Gate
        allowed, policy_banner = enforce_version_policy(config=config)
        if not allowed:
            if config.json_output or config.json_stream:
                print(json.dumps({"success": False, "error": "version_deprecated", "message": policy_banner}))
            else:
                print(policy_banner, file=sys.stderr)
            return 1
        elif "reached End of Life" in policy_banner:
            if not config.json_output and not config.json_stream:
                print(policy_banner)

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

        # Channel / Playlist Subscriptions
        if getattr(args, "subscribe", None):
            sub_url = clean_protocol_url(str(args.subscribe).strip())
            sub = add_subscription(
                db_path,
                sub_url,
                audio_only=config.audio_only,
                quality=config.quality,
                max_downloads=config.max_downloads or 5,
            )
            if config.json_output or config.json_stream:
                print(json.dumps({"success": True, "subscription": sub}, indent=2))
            else:
                success(f"Subscribed (#{sub['id']}): {sub['url']}", config)
            return 0

        if getattr(args, "unsubscribe", None):
            removed = remove_subscription(db_path, str(args.unsubscribe).strip())
            if config.json_output or config.json_stream:
                print(json.dumps({"success": removed, "target": str(args.unsubscribe)}))
            else:
                if removed:
                    success(f"Removed subscription: {args.unsubscribe}", config)
                else:
                    warning(f"No matching subscription found for: {args.unsubscribe}", config)
            return 0 if removed else 1

        if getattr(args, "list_subscriptions", False):
            subs = list_subscriptions(db_path)
            if config.json_output or config.json_stream:
                print(json.dumps({"success": True, "count": len(subs), "subscriptions": subs}, indent=2))
            else:
                print_banner(config)
                if not subs:
                    info("No active subscriptions configured.", config)
                else:
                    print(f"{'ID':<5} {'QUALITY':<10} {'MAX':<6} {'LAST SYNCED':<20} {'URL'}")
                    print("-" * 90)
                    for s in subs:
                        q_label = "audio" if s["audio_only"] else s["quality"]
                        synced_str = (s.get("last_synced_at") or "Never")[:19]
                        print(f"{s['id']:<5} {q_label:<10} {s['max_downloads']:<6} {synced_str:<20} {s['url']}")
                    print("-" * 90)
            return 0

        if getattr(args, "sync_subscriptions", False):
            summary = sync_subscriptions(config, db_path)
            if config.json_output or config.json_stream:
                print(json.dumps({"success": summary["failed"] == 0, **summary}, indent=2))
            else:
                print_banner(config)
                if summary["total"] == 0:
                    info("No subscriptions configured. Add one with --subscribe <URL>.", config)
                else:
                    success(
                        f"Subscriptions sync complete: {summary['synced']}/{summary['total']} succeeded ({summary['failed']} failed).",
                        config,
                    )
            return 0 if summary["failed"] == 0 else 1

        # Clipboard Watcher Daemon
        if getattr(args, "watch_clipboard", False):
            watch_clipboard(engine, interval=config.watch_interval)
            return 0

        requested_url = validate_url_option(args)
        if requested_url:
            requested_url = clean_protocol_url(requested_url)

        # Search mode
        if getattr(args, "search", None):
            query = str(args.search).strip()
            limit = getattr(args, "search_limit", 10) or 10
            try:
                results = search_youtube(query, limit=limit, proxy=config.proxy, timeout=config.timeout)
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": True, "query": query, "count": len(results), "results": results}, indent=2))
                else:
                    print_banner(config)
                    if not results:
                        info(f"No results found for '{query}'.", config)
                    else:
                        info(f"Found {len(results)} results for '{query}':", config)
                        print("-" * 80)
                        for idx, r in enumerate(results, start=1):
                            dur = f" ({r['duration_string']})" if r.get("duration_string") else ""
                            uploader = f" • {r['uploader']}" if r.get("uploader") else ""
                            print(f"[{idx:2d}] {r['title']}{uploader}{dur}")
                            print(f"     URL: {r['url']}")
                        print("-" * 80)
                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "query": query, "error": str(exc)}))
                else:
                    failure(f"Search failed: {exc}", config)
                return 1

        # Suggestions mode
        if getattr(args, "suggest", None):
            query = str(args.suggest).strip()
            try:
                suggestions = fetch_suggestions(query, timeout=config.timeout)
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": True, "query": query, "suggestions": suggestions}, indent=2))
                else:
                    for item in suggestions:
                        print(item)
                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "query": query, "error": str(exc)}))
                else:
                    failure(f"Suggestion lookup failed: {exc}", config)
                return 1

        # Generic webpage media sniffer mode
        if getattr(args, "sniff", None):
            page_url = clean_protocol_url(str(args.sniff).strip())
            try:
                discovered = sniff_page_media(page_url, timeout=config.timeout)
                payload = {
                    "success": True,
                    "url": page_url,
                    "count": len(discovered),
                    "media": [m.to_dict() for m in discovered],
                }
                if config.json_output or config.json_stream:
                    print(json.dumps(payload, indent=2))
                else:
                    print_banner(config)
                    if not discovered:
                        info(f"No embedded media streams found on {page_url}.", config)
                    else:
                        info(f"Discovered {len(discovered)} embedded media item(s):", config)
                        print("-" * 80)
                        for idx, item in enumerate(discovered, start=1):
                            mime = f" ({item.mime_type})" if item.mime_type else ""
                            print(f"[{idx:2d}] [{item.media_type.upper()}] via {item.source}{mime}")
                            print(f"     URL: {item.url}")
                        print("-" * 80)
                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "url": page_url, "error": str(exc)}))
                else:
                    failure(f"Media sniff failed: {exc}", config)
                return 1

        # Direct local media conversion / audio extraction mode
        convert_fmt = (
            getattr(args, "convert", None)
            or getattr(args, "convert_audio", None)
            or getattr(args, "convert_video", None)
        )
        local_remux_fmt = None
        if not convert_fmt and requested_url and getattr(args, "remux_video", None):
            try:
                if Path(requested_url).expanduser().is_file():
                    local_remux_fmt = args.remux_video
            except OSError:
                pass

        if convert_fmt or local_remux_fmt:
            target_fmt = convert_fmt or local_remux_fmt
            if not requested_url:
                err_msg = "Please provide a local media file path to convert."
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": err_msg}))
                else:
                    failure(err_msg, config)
                return 1
            try:
                out_dir = Path(args.output).expanduser() if getattr(args, "output", None) else None
                converted_path = convert_media_file(
                    Path(requested_url),
                    str(target_fmt),
                    output_dir=out_dir,
                    audio_quality=config.audio_quality,
                    remux_only=bool(local_remux_fmt),
                    normalize_audio=config.normalize_audio,
                )
                if config.json_output or config.json_stream:
                    print(
                        json.dumps(
                            {
                                "success": True,
                                "input": str(Path(requested_url).expanduser()),
                                "output": str(converted_path),
                                "format": str(target_fmt),
                            },
                            indent=2,
                        )
                    )
                else:
                    success(f"Converted media saved: {converted_path}", config)
                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(exc)}))
                else:
                    failure(f"Media conversion failed: {exc}", config)
                return 1

        # Direct local GIF conversion
        if getattr(args, "to_gif", False) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    out_path = video_to_gif(
                        local_path,
                        start_time=config.start_time,
                        duration=config.record_duration,
                        fps=config.gif_fps,
                        width=config.gif_width,
                    )
                    if config.json_output or config.json_stream:
                        print(json.dumps({"success": True, "output": str(out_path)}))
                    else:
                        success(f"GIF created: {out_path}", config)
                    return 0
            except Exception as gexc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(gexc)}))
                else:
                    failure(f"GIF generation failed: {gexc}", config)
                return 1

        # Direct local frame grab / screenshot
        if getattr(args, "frame_grab", None) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    out_path = extract_frame(
                        local_path,
                        timestamp=str(args.frame_grab),
                    )
                    if config.json_output or config.json_stream:
                        print(json.dumps({"success": True, "output": str(out_path)}))
                    else:
                        success(f"Frame extracted: {out_path}", config)
                    return 0
            except Exception as fexc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(fexc)}))
                else:
                    failure(f"Frame extraction failed: {fexc}", config)
                return 1

        # Direct local video clip extraction
        if getattr(args, "make_clip", False) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    if not config.start_time:
                        raise ValueError("Clipping requires --start-time (e.g. --start-time 00:00:10)")
                    out_path = create_clip(
                        local_path,
                        start_time=config.start_time,
                        end_time=config.end_time,
                        duration=config.record_duration,
                    )
                    if config.json_output or config.json_stream:
                        print(json.dumps({"success": True, "output": str(out_path)}))
                    else:
                        success(f"Clip extracted: {out_path}", config)
                    return 0
            except Exception as cexc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(cexc)}))
                else:
                    failure(f"Clip extraction failed: {cexc}", config)
                return 1

        # Direct local music tagging
        if getattr(args, "tag_music", False) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    from universal_downloader.music_tagger import auto_tag_music
                    meta = auto_tag_music(local_path)
                    if config.json_output or config.json_stream:
                        print(json.dumps({"success": True, "metadata": meta, "file": str(local_path)}))
                    else:
                        if meta:
                            success(f"Tagged '{local_path.name}': {meta.get('artist')} - {meta.get('title')} ({meta.get('album')})", config)
                        else:
                            warning(f"No MusicBrainz match found for '{local_path.name}'.", config)
                    return 0
            except Exception as texc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(texc)}))
                else:
                    failure(f"Music tagging failed: {texc}", config)
                return 1

        # Direct local file compression via preset
        if getattr(args, "preset", None) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    from universal_downloader.presets import compress_video_to_target_size, get_preset
                    preset_obj = get_preset(args.preset)
                    if preset_obj and preset_obj.max_size_mb:
                        out_path = compress_video_to_target_size(local_path, target_mb=preset_obj.max_size_mb)
                        if config.json_output or config.json_stream:
                            print(json.dumps({"success": True, "output": str(out_path), "preset": preset_obj.id}))
                        else:
                            success(f"Video compressed to fit under {preset_obj.max_size_mb}MB: {out_path}", config)
                        return 0
            except Exception as pexc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(pexc)}))
                else:
                    failure(f"Preset compression failed: {pexc}", config)
                return 1

        # Direct local file sharing over Wi-Fi with QR code
        if getattr(args, "share", False) and requested_url:
            try:
                local_path = Path(requested_url).expanduser()
                if local_path.is_file():
                    from universal_downloader.local_share import generate_qr_ascii, start_file_share
                    server = start_file_share(local_path, port=config.share_port)
                    qr_text = generate_qr_ascii(server.url)
                    if config.json_output or config.json_stream:
                        print(json.dumps({"success": True, "share_url": server.url, "file": str(local_path)}))
                    else:
                        print("\n" + "=" * 60)
                        print(f"📲 Sharing '{local_path.name}' over Local Wi-Fi")
                        print(f"👉 Scan QR code with your phone camera or visit:")
                        print(f"   {server.url}")
                        print("=" * 60)
                        print(qr_text)
                        print("Press Ctrl+C to stop sharing.\n")
                    try:
                        while True:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        server.stop()
                        print("\nSharing stopped.")
                    return 0
            except Exception as sexc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(sexc)}))
                else:
                    failure(f"File sharing failed: {sexc}", config)
                return 1

        # Metadata inspection mode
        if getattr(args, "metadata", None):
            meta_url = clean_protocol_url(args.metadata)
            try:
                target = detect_target(meta_url, timeout=config.timeout)
                if target.content_type == ContentType.PROFILE and target.platform in {
                    Platform.FACEBOOK,
                    Platform.INSTAGRAM,
                    Platform.TIKTOK,
                    Platform.TWITTER,
                    Platform.THREADS,
                    Platform.BLUESKY,
                    Platform.REDDIT,
                    Platform.YOUTUBE,
                }:
                    inspection = inspect_profile_images_detailed(
                        target.normalized_url,
                        platform=target.platform,
                        config=config,
                        extractor=engine.extractor,
                    )
                    verified_imgs = inspection.images
                    username = extract_username_from_profile_url(target.normalized_url, target.platform) or "Profile"
                    qualities = [
                        f"{img.width}x{img.height}"
                        for img in verified_imgs
                        if img.width and img.height
                    ]
                    payload = {
                        "url": target.normalized_url,
                        "platform": target.platform.value,
                        "title": inspection.title or username,
                        "uploader": username,
                        "duration": None,
                        "duration_string": None,
                        "thumbnail": verified_imgs[0].url if verified_imgs else None,
                        "description": inspection.bio
                        or inspection.profile_notice
                        or "Profile page — use 'Inspect Streams' to view all available picture resolutions or click 'Profile Pic'.",
                        "view_count": None,
                        "is_playlist": False,
                        "playlist_count": 0,
                        "qualities": qualities,
                        "codecs": [],
                        "is_profile": True,
                        "entries": [],
                        "profile_locked": inspection.profile_locked,
                        "profile_notice": inspection.profile_notice,
                        "profile_id": inspection.profile_id,
                        "bio": inspection.bio,
                        "is_verified": inspection.is_verified,
                        "profile_info": [item.to_dict() for item in inspection.profile_info],
                    }
                    if config.json_output or config.json_stream:
                        print(json.dumps(payload, indent=2))
                    else:
                        print(f"Title:     {payload['title']}")
                        print(f"Uploader:  {payload['uploader']}")
                        print(f"Thumbnail: {payload['thumbnail']}")
                    return 0

                is_pl = target.content_type == ContentType.PLAYLIST
                info_data = engine.inspect(
                    target.normalized_url,
                    platform=target.platform,
                    flat_playlist=is_pl,
                )
                entries = [e for e in (info_data.get("entries") or []) if isinstance(e, dict)]
                uploader = (
                    info_data.get("uploader")
                    or info_data.get("channel")
                    or info_data.get("creator")
                    or "Unknown Creator"
                )
                playlist_entries = _build_playlist_entries(entries, target.platform, uploader) if entries else []
                is_playlist_result = bool(playlist_entries) and (is_pl or len(playlist_entries) > 1)
                title = info_data.get("title") or "Unknown Title"

                thumb = _pick_thumbnail(info_data, target.platform)
                if not thumb and playlist_entries:
                    thumb = playlist_entries[0].get("thumbnail")

                payload = {
                    "url": target.normalized_url,
                    "platform": target.platform.value,
                    "title": title,
                    "uploader": uploader,
                    "duration": info_data.get("duration"),
                    "duration_string": info_data.get("duration_string"),
                    "thumbnail": thumb,
                    "description": (info_data.get("description") or "")[:500],
                    "view_count": info_data.get("view_count"),
                    "is_playlist": is_playlist_result,
                    "playlist_count": len(playlist_entries),
                    "qualities": _extract_supported_qualities(info_data),
                    "codecs": _extract_supported_codecs(info_data),
                    "is_profile": False,
                    "entries": playlist_entries if is_playlist_result else [],
                }
                if config.json_output or config.json_stream:
                    print(json.dumps(payload, indent=2))
                else:
                    print(f"Title:     {payload['title']}")
                    print(f"Uploader:  {payload['uploader']}")
                    print(f"Duration:  {payload['duration_string']}")
                    print(f"Thumbnail: {payload['thumbnail']}")
                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(exc)}))
                else:
                    failure(f"Failed to inspect metadata: {exc}", config)
                return 1

        # Direct profile image URL download mode (used by Inspect Streams image selection)
        if getattr(args, "profile_image_url", None):
            img_url = clean_protocol_url(args.profile_image_url)
            src_url = getattr(args, "profile_source_url", None)
            enhance_hd = bool(getattr(args, "enhance_hd", False))
            try:
                saved = download_direct_profile_image(
                    img_url,
                    config,
                    source_profile_url=src_url,
                    enhance_hd=enhance_hd,
                )
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": True, "saved_profile": str(saved)}))
                else:
                    success(f"Image saved: {saved}", config)
                return 0
            except (ProfileError, Exception) as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(exc)}))
                else:
                    failure(f"Image download failed: {exc}", config)
                return 1

        # Formats inspection mode
        if args.formats:
            fmt_url = clean_protocol_url(args.formats)
            try:
                # Allow platform:username shorthand in Inspect Streams too
                if "://" not in fmt_url and not fmt_url.startswith("www.") and ":" in fmt_url:
                    fmt_url = resolve_profile_input(fmt_url)

                target = detect_target(fmt_url, timeout=config.timeout)

                if target.content_type == ContentType.PROFILE:
                    inspection = inspect_profile_images_detailed(
                        target.normalized_url,
                        platform=target.platform,
                        config=config,
                        extractor=engine.extractor,
                    )
                    verified_imgs = inspection.images
                    formats_data = [img.to_format_dict(idx) for idx, img in enumerate(verified_imgs)]
                    if config.json_output or config.json_stream:
                        print(
                            json.dumps(
                                {
                                    "url": target.normalized_url,
                                    "formats": formats_data,
                                    "profile_locked": inspection.profile_locked,
                                    "profile_notice": inspection.profile_notice,
                                    "profile_id": inspection.profile_id,
                                    "bio": inspection.bio,
                                    "is_verified": inspection.is_verified,
                                    "profile_info": [item.to_dict() for item in inspection.profile_info],
                                },
                                indent=2,
                            )
                        )
                    else:
                        print_banner(config)
                        print(f"Profile:  {target.normalized_url}")
                        print(f"Pictures: {len(formats_data)} verified image(s)")
                        if inspection.profile_notice:
                            print(f"Notice:   {inspection.profile_notice}")
                        for item in formats_data:
                            print(f"  - {item['format_id']}: {item['resolution']} ({item['ext']}) - {item['format_note']}")
                    return 0

                is_pl = target.content_type == ContentType.PLAYLIST

                if not config.json_output and not config.json_stream:
                    print_banner(config)
                    print(f"URL:      {target.normalized_url}")
                    print(f"Platform: {target.platform.value}")
                    print()

                info_data = engine.inspect(
                    target.normalized_url,
                    platform=target.platform,
                    playlist_items="1" if is_pl else None,
                )
                if is_pl and isinstance(info_data.get("entries"), list):
                    valid_entries = [e for e in info_data["entries"] if isinstance(e, dict)]
                    if valid_entries:
                        info_data = valid_entries[0]

                if config.json_output or config.json_stream:
                    formats_data = [fmt.raw for fmt in parse_format(info_data)]
                    print(json.dumps({"url": target.normalized_url, "formats": formats_data}, indent=2))
                else:
                    print(f"Title: {info_data.get('title') or 'unknown'}")
                    print_formats(info_data, config)

                return 0
            except Exception as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"url": fmt_url, "formats": [], "error": str(exc)}))
                else:
                    failure(f"Failed to inspect formats: {exc}", config)
                return 1

        # Profile picture resolution mode
        if args.profile:
            prof_val = clean_protocol_url(args.profile)
            try:
                if not config.json_output and not config.json_stream:
                    print_banner(config)

                saved = engine.download_profile(prof_val)

                if config.json_output or config.json_stream:
                    print(json.dumps({"success": True, "saved_profile": str(saved)}))
                else:
                    success(f"Profile picture saved: {saved}", config)

                return 0
            except (ProfileError, Exception) as exc:
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": str(exc)}))
                else:
                    failure(f"Profile picture download failed: {exc}", config)
                return 1

        # Smart Scheduling Gate
        if config.schedule:
            try:
                from universal_downloader.smart_scheduler import seconds_until_schedule, wait_until_schedule
                secs = seconds_until_schedule(config.schedule)
                if not config.json_output and not config.json_stream:
                    info(f"Scheduled download: Waiting until {config.schedule} ({secs}s remaining)...", config)
                wait_until_schedule(config.schedule)
                if not config.json_output and not config.json_stream:
                    success(f"Scheduled time {config.schedule} reached! Starting download...", config)
            except Exception as exc:
                error(f"Scheduling failed: {exc}", config)
                return 1

        # Smart Power / Battery Saver Gate
        if config.pause_on_battery:
            from universal_downloader.smart_scheduler import check_smart_download_conditions
            can_proceed, reason = check_smart_download_conditions(pause_on_battery=True)
            if not can_proceed:
                warning(reason, config)
                if config.json_output or config.json_stream:
                    print(json.dumps({"success": False, "error": "battery_low", "message": reason}))
                return 2

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
            # Standalone local file transcription
            if getattr(args, "transcribe", False) and Path(requested_url).is_file():
                from universal_downloader.transcriber import transcribe_media
                formats_tuple = tuple(fmt.strip() for fmt in config.transcribe_format.split(",") if fmt.strip())
                out_files = transcribe_media(
                    Path(requested_url),
                    model_name=config.whisper_model,
                    language=config.whisper_lang,
                    formats=formats_tuple,
                    summarize=config.summarize,
                )
                if config.preset and result.files:
                    from universal_downloader.presets import compress_video_to_target_size, get_preset
                    preset_obj = get_preset(config.preset)
                    if preset_obj and preset_obj.max_size_mb:
                        compressed_list = []
                        for f in result.files:
                            if f.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}:
                                try:
                                    compressed = compress_video_to_target_size(f, target_mb=preset_obj.max_size_mb)
                                    compressed_list.append(compressed)
                                except Exception as c_exc:
                                    LOGGER.warning(f"Target size compression warning: {c_exc}")
                                    compressed_list.append(f)
                            else:
                                compressed_list.append(f)
                        result.files = compressed_list

                if config.json_output:
                    print(json.dumps({"success": True, "files": [str(p) for p in out_files.values()]}))
                else:
                    success("Transcription complete:", config)
                    for fmt, p in out_files.items():
                        print(f"  • {fmt.upper()}: {p}")
                return 0

            if not config.json_output and not config.json_stream:
                print_banner(config)

            try:
                target = detect_target(requested_url, timeout=config.timeout)

                # Apply deep-link format hint if user provided #ID/format or url#format
                if target.format_hint:
                    hint = target.format_hint.lower()
                    if hint in {"mp3", "audio", "m4a", "flac", "opus", "wav", "aac"}:
                        config.audio_only = True
                        if hint in {"mp3", "m4a", "flac", "opus", "wav", "aac"} and not getattr(args, "audio_format", None):
                            config.audio_format = hint
                    elif hint in {"mp4", "video"}:
                        config.audio_only = False
                        if hint == "mp4" and not getattr(args, "remux_video", None):
                            config.remux_video = "mp4"

                if not config.json_output and not config.json_stream:
                    print(f"URL:      {target.normalized_url}")
                    print(f"Platform: {target.platform.value}")
                    print(f"Type:     {target.content_type.value}")
                    print()
                    info("Processing...", config)

                result = engine.download(target.normalized_url)

                if config.preset and result.files:
                    from universal_downloader.presets import compress_video_to_target_size, get_preset
                    preset_obj = get_preset(config.preset)
                    if preset_obj and preset_obj.max_size_mb:
                        compressed_list = []
                        for f in result.files:
                            if f.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}:
                                try:
                                    compressed = compress_video_to_target_size(f, target_mb=preset_obj.max_size_mb)
                                    compressed_list.append(compressed)
                                except Exception as c_exc:
                                    LOGGER.warning(f"Target size compression warning: {c_exc}")
                                    compressed_list.append(f)
                            else:
                                compressed_list.append(f)
                        result.files = compressed_list

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
                if target is None and is_valid_search_query(requested_url) and "://" not in requested_url and not requested_url.startswith("www."):
                    try:
                        results = search_youtube(
                            requested_url,
                            limit=getattr(args, "search_limit", 10) or 10,
                            proxy=config.proxy,
                            timeout=config.timeout,
                        )
                        if config.json_output or config.json_stream:
                            print(json.dumps({"success": True, "query": requested_url, "count": len(results), "results": results}, indent=2))
                        else:
                            info(f"Input is not a URL. Found {len(results)} YouTube search results for '{requested_url}':", config)
                            print("-" * 80)
                            for s_idx, s_r in enumerate(results, start=1):
                                s_dur = f" ({s_r['duration_string']})" if s_r.get("duration_string") else ""
                                s_up = f" • {s_r['uploader']}" if s_r.get("uploader") else ""
                                print(f"[{s_idx:2d}] {s_r['title']}{s_up}{s_dur}")
                                print(f"     URL: {s_r['url']}")
                            print("-" * 80)
                        return 0
                    except Exception:
                        pass

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
        try:
            from universal_downloader.telemetry import send_crash_report
            send_crash_report(exc, client_platform="CLI", async_send=False)
        except Exception:
            pass
        print(f"✗ Unexpected application error\n\n{exc}", file=sys.stderr)
        return 1
