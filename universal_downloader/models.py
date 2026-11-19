"""Data structures, enums, and configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from universal_downloader.paths import get_default_log_dir


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
    BILIBILI = "bilibili"
    BLUESKY = "bluesky"
    BANDCAMP = "bandcamp"
    LOOM = "loom"
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


@dataclass
class AppConfig:
    output_dir: Path = Path("downloads")
    log_dir: Path = field(default_factory=get_default_log_dir)
    retries: int = 3
    timeout: int = 30
    quality: str = "best"
    audio_only: bool = False
    audio_format: str = "mp3"
    audio_quality: str = "192k"
    normalize_audio: bool = False
    write_metadata: bool = True
    embed_metadata: bool = False
    embed_thumbnail: bool = False
    write_subs: bool = False
    embed_subs: bool = False
    sub_langs: Optional[str] = None
    auto_subs: bool = False
    output_template: Optional[str] = None
    organize: str = "platform"
    clean_filenames: bool = False
    verify_integrity: bool = False
    write_checksum: bool = False
    download_archive: Optional[Path] = None
    concurrency: int = 1
    limit_rate: Optional[str] = None
    sleep_interval: int = 0
    max_sleep_interval: Optional[int] = None
    proxy: Optional[str] = None
    geo_bypass: bool = False
    sponsorblock_remove: Optional[str] = None
    split_chapters: bool = False
    remux_video: Optional[str] = None
    playlist_items: Optional[str] = None
    max_downloads: Optional[int] = None
    dry_run: bool = False
    json_output: bool = False
    json_stream: bool = False
    download_sections: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    record_duration: Optional[str] = None
    live_from_start: bool = False
    concurrent_fragments: int = 4
    prefer_codec: Optional[str] = None
    min_filesize: Optional[str] = None
    max_filesize: Optional[str] = None
    write_thumbnail: bool = False
    no_history: bool = False
    no_telemetry: bool = False
    telemetry_url: Optional[str] = None
    telemetry_key: Optional[str] = None
    friend_tag: Optional[str] = None
    notify: bool = False
    watch_clipboard: bool = False
    watch_interval: float = 1.0
    verbose: bool = False
    debug: bool = False
    no_color: bool = False
    no_check_certificate: bool = False
    cookies_file: Optional[Path] = None
    cookies_from_browser: Optional[str] = None
    force_deprecated: bool = False
    schedule: Optional[str] = None
    pause_on_battery: bool = False
    only_wifi: bool = False
    aria2: bool = False
    transcribe: bool = False
    whisper_model: str = "base"
    whisper_lang: Optional[str] = None
    transcribe_format: str = "srt,txt,vtt"
    summarize: bool = False


@dataclass
class DetectedTarget:
    original_url: str
    normalized_url: str
    platform: Platform
    content_type: ContentType = ContentType.UNKNOWN
    is_profile_candidate: bool = False
    format_hint: Optional[str] = None


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchSummary:
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
