"""Configuration parsing from CLI arguments, environment variables, and configuration files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Optional

from universal_downloader.exceptions import ConfigurationError
from universal_downloader.models import AppConfig
from universal_downloader.paths import (
    get_default_data_dir,
    get_default_download_dir,
    get_default_log_dir,
    is_directory_writable,
    is_system_or_program_dir,
)


def parse_dotenv(path: Path) -> dict[str, str]:
    """Small dependency-free .env parser supporting KEY=VALUE pairs."""
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


def parse_config_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def build_config(args: argparse.Namespace) -> AppConfig:
    dotenv = parse_dotenv(Path(".env"))
    json_config = load_json_config(Path("config.json"))

    output_raw = (
        getattr(args, "output", None)
        or env_value(dotenv, "DOWNLOAD_DIR")
        or json_config.get("download_dir")
    )
    if output_raw:
        output_dir = Path(output_raw).expanduser()
    else:
        cwd = Path.cwd()
        if not is_system_or_program_dir(cwd) and is_directory_writable(cwd):
            output_dir = Path("downloads")
        else:
            output_dir = get_default_download_dir()

    retries_value = (
        args.retries
        if getattr(args, "retries", None) is not None
        else parse_config_int(
            env_value(dotenv, "RETRIES") or json_config.get("retries", 3),
            "retries",
            3,
        )
    )

    timeout_value = (
        args.timeout
        if getattr(args, "timeout", None) is not None
        else parse_config_int(
            env_value(dotenv, "TIMEOUT") or json_config.get("timeout", 30),
            "timeout",
            30,
        )
    )

    quality = (
        getattr(args, "quality", None)
        or env_value(dotenv, "QUALITY")
        or json_config.get("quality")
        or "best"
    )

    audio_only = (
        getattr(args, "audio_only", False)
        or parse_config_bool(env_value(dotenv, "AUDIO_ONLY"))
        or parse_config_bool(json_config.get("audio_only"))
    )

    audio_format = (
        getattr(args, "audio_format", None)
        or env_value(dotenv, "AUDIO_FORMAT")
        or json_config.get("audio_format")
        or "mp3"
    )

    audio_quality = (
        getattr(args, "audio_quality", None)
        or env_value(dotenv, "AUDIO_QUALITY")
        or json_config.get("audio_quality")
        or "192k"
    )

    # Metadata & Artwork
    write_metadata = (
        not getattr(args, "no_metadata", False)
        if getattr(args, "no_metadata", False)
        else parse_config_bool(
            env_value(dotenv, "WRITE_METADATA"),
            json_config.get("write_metadata", True),
        )
    )

    embed_metadata = (
        getattr(args, "embed_metadata", False)
        or parse_config_bool(env_value(dotenv, "EMBED_METADATA"))
        or parse_config_bool(json_config.get("embed_metadata"))
    )

    embed_thumbnail = (
        getattr(args, "embed_thumbnail", False)
        or parse_config_bool(env_value(dotenv, "EMBED_THUMBNAIL"))
        or parse_config_bool(json_config.get("embed_thumbnail"))
    )

    # Subtitles
    write_subs = (
        getattr(args, "write_subs", False)
        or parse_config_bool(env_value(dotenv, "WRITE_SUBS"))
        or parse_config_bool(json_config.get("write_subs"))
    )

    embed_subs = (
        getattr(args, "embed_subs", False)
        or parse_config_bool(env_value(dotenv, "EMBED_SUBS"))
        or parse_config_bool(json_config.get("embed_subs"))
    )

    sub_langs = (
        getattr(args, "sub_langs", None)
        or env_value(dotenv, "SUB_LANGS")
        or json_config.get("sub_langs")
    )

    auto_subs = (
        getattr(args, "auto_subs", False)
        or parse_config_bool(env_value(dotenv, "AUTO_SUBS"))
        or parse_config_bool(json_config.get("auto_subs"))
    )

    # Templates & Paths
    output_template = (
        getattr(args, "output_template", None)
        or env_value(dotenv, "OUTPUT_TEMPLATE")
        or json_config.get("output_template")
    )

    organize = (
        getattr(args, "organize", None)
        or env_value(dotenv, "ORGANIZE")
        or json_config.get("organize")
        or "platform"
    ).strip().lower()
    if organize not in {"none", "platform", "uploader", "date"}:
        raise ConfigurationError(
            f"Invalid organize mode '{organize}'. Expected one of: none, platform, uploader, date."
        )

    clean_filenames = (
        getattr(args, "clean_filenames", False)
        or parse_config_bool(env_value(dotenv, "CLEAN_FILENAMES"))
        or parse_config_bool(json_config.get("clean_filenames"))
    )

    download_archive_val = (
        getattr(args, "download_archive", None)
        or env_value(dotenv, "DOWNLOAD_ARCHIVE")
        or json_config.get("download_archive")
    )

    # Concurrency & Networking
    concurrency_val = (
        args.concurrency
        if getattr(args, "concurrency", None) is not None
        else parse_config_int(
            env_value(dotenv, "CONCURRENCY")
            or json_config.get("concurrency", 1),
            "concurrency",
            1,
        )
    )

    limit_rate = (
        getattr(args, "limit_rate", None)
        or env_value(dotenv, "LIMIT_RATE")
        or json_config.get("limit_rate")
    )

    sleep_interval_val = (
        args.sleep_interval
        if getattr(args, "sleep_interval", None) is not None
        else parse_config_int(
            env_value(dotenv, "SLEEP_INTERVAL")
            or json_config.get("sleep_interval", 0),
            "sleep_interval",
            0,
        )
    )

    max_sleep_interval_val = getattr(args, "max_sleep_interval", None)
    if max_sleep_interval_val is None:
        raw_max = env_value(dotenv, "MAX_SLEEP_INTERVAL") or json_config.get("max_sleep_interval")
        max_sleep_interval_val = int(raw_max) if raw_max is not None else None

    proxy = (
        getattr(args, "proxy", None)
        or env_value(dotenv, "PROXY")
        or json_config.get("proxy")
    )

    geo_bypass = (
        getattr(args, "geo_bypass", False)
        or parse_config_bool(env_value(dotenv, "GEO_BYPASS"))
        or parse_config_bool(json_config.get("geo_bypass"))
    )

    sponsorblock_remove = (
        getattr(args, "sponsorblock_remove", None)
        or env_value(dotenv, "SPONSORBLOCK_REMOVE")
        or json_config.get("sponsorblock_remove")
    )

    split_chapters = (
        getattr(args, "split_chapters", False)
        or parse_config_bool(env_value(dotenv, "SPLIT_CHAPTERS"))
        or parse_config_bool(json_config.get("split_chapters"))
    )

    remux_video = (
        getattr(args, "remux_video", None)
        or env_value(dotenv, "REMUX_VIDEO")
        or json_config.get("remux_video")
    )

    playlist_items = (
        getattr(args, "playlist_items", None)
        or env_value(dotenv, "PLAYLIST_ITEMS")
        or json_config.get("playlist_items")
    )

    max_downloads_val = getattr(args, "max_downloads", None)
    if max_downloads_val is None:
        raw_max_dl = env_value(dotenv, "MAX_DOWNLOADS") or json_config.get("max_downloads")
        max_downloads_val = int(raw_max_dl) if raw_max_dl is not None else None

    # Cookies
    cookies_file_value = (
        getattr(args, "cookies", None)
        or env_value(dotenv, "COOKIES_FILE")
        or json_config.get("cookies_file")
    )

    cookies_browser_value = (
        getattr(args, "cookies_from_browser", None)
        or env_value(dotenv, "COOKIES_FROM_BROWSER")
        or json_config.get("cookies_from_browser")
    )

    log_raw = env_value(dotenv, "LOG_DIR") or json_config.get("log_dir")
    if log_raw:
        log_dir = Path(log_raw).expanduser()
    else:
        local_logs = Path("logs")
        if (
            local_logs.is_dir()
            and not is_system_or_program_dir(Path.cwd())
            and is_directory_writable(local_logs)
        ):
            log_dir = local_logs
        else:
            log_dir = get_default_log_dir()

    config = AppConfig(
        output_dir=output_dir,
        log_dir=log_dir,
        retries=max(0, retries_value),
        timeout=max(1, timeout_value),
        quality=quality,
        audio_only=audio_only,
        audio_format=audio_format.lower().lstrip("."),
        audio_quality=audio_quality,
        write_metadata=write_metadata,
        embed_metadata=embed_metadata,
        embed_thumbnail=embed_thumbnail,
        write_subs=write_subs,
        embed_subs=embed_subs,
        sub_langs=sub_langs,
        auto_subs=auto_subs,
        output_template=output_template,
        organize=organize,
        clean_filenames=clean_filenames,
        download_archive=Path(download_archive_val).expanduser() if download_archive_val else None,
        concurrency=max(1, min(16, concurrency_val)),
        limit_rate=limit_rate,
        sleep_interval=max(0, sleep_interval_val),
        max_sleep_interval=max_sleep_interval_val,
        proxy=proxy,
        geo_bypass=geo_bypass,
        sponsorblock_remove=sponsorblock_remove,
        split_chapters=split_chapters,
        remux_video=remux_video,
        playlist_items=playlist_items,
        max_downloads=max_downloads_val,
        concurrent_fragments=getattr(args, "concurrent_fragments", None) or parse_config_int(env_value(dotenv, "CONCURRENT_FRAGMENTS") or json_config.get("concurrent_fragments", 4), "concurrent_fragments", 4),
        prefer_codec=getattr(args, "prefer_codec", None) or env_value(dotenv, "PREFER_CODEC") or json_config.get("prefer_codec"),
        download_sections=getattr(args, "download_sections", None) or env_value(dotenv, "DOWNLOAD_SECTIONS") or json_config.get("download_sections"),
        start_time=getattr(args, "start_time", None) or env_value(dotenv, "START_TIME") or json_config.get("start_time"),
        end_time=getattr(args, "end_time", None) or env_value(dotenv, "END_TIME") or json_config.get("end_time"),
        record_duration=getattr(args, "record_duration", None) or env_value(dotenv, "RECORD_DURATION") or json_config.get("record_duration"),
        live_from_start=getattr(args, "live_from_start", False) or parse_config_bool(env_value(dotenv, "LIVE_FROM_START")) or parse_config_bool(json_config.get("live_from_start")),
        min_filesize=getattr(args, "min_filesize", None) or env_value(dotenv, "MIN_FILESIZE") or json_config.get("min_filesize"),
        max_filesize=getattr(args, "max_filesize", None) or env_value(dotenv, "MAX_FILESIZE") or json_config.get("max_filesize"),
        write_thumbnail=getattr(args, "write_thumbnail", False) or parse_config_bool(env_value(dotenv, "WRITE_THUMBNAIL")) or parse_config_bool(json_config.get("write_thumbnail")),
        no_history=getattr(args, "no_history", False) or parse_config_bool(env_value(dotenv, "NO_HISTORY")) or parse_config_bool(json_config.get("no_history")),
        notify=getattr(args, "notify", False) or parse_config_bool(env_value(dotenv, "NOTIFY")) or parse_config_bool(json_config.get("notify")),
        watch_clipboard=getattr(args, "watch_clipboard", False),
        watch_interval=float(getattr(args, "watch_interval", 1.0) or 1.0),
        dry_run=getattr(args, "dry_run", False),
        json_output=getattr(args, "json_output", False),
        json_stream=getattr(args, "json_stream", False),
        verbose=getattr(args, "verbose", False),
        debug=getattr(args, "debug", False),
        no_color=getattr(args, "no_color", False),
        no_check_certificate=getattr(args, "no_check_certificate", False) or parse_config_bool(json_config.get("no_check_certificate")),
        cookies_file=Path(cookies_file_value).expanduser() if cookies_file_value else None,
        cookies_from_browser=cookies_browser_value.strip() if cookies_browser_value else None,
    )

    if config.retries > 20:
        raise ConfigurationError("Retries must not exceed 20.")

    if config.timeout > 3600:
        raise ConfigurationError("Timeout must not exceed 3600 seconds.")

    return config


def generate_default_config(target_dir: Path) -> tuple[Path, Path]:
    """Generate default .env and config.json files for easy configuration."""
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "config.json"
    env_path = target_dir / ".env"

    default_json = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "download_dir": "downloads",
        "log_dir": "logs",
        "retries": 3,
        "timeout": 30,
        "quality": "best",
        "audio_only": False,
        "audio_format": "mp3",
        "audio_quality": "192k",
        "write_metadata": True,
        "embed_metadata": False,
        "embed_thumbnail": False,
        "write_subs": False,
        "embed_subs": False,
        "sub_langs": "en",
        "auto_subs": False,
        "output_template": "%(uploader)s - %(title).150B [%(id)s].%(ext)s",
        "download_archive": None,
        "concurrency": 1,
        "limit_rate": None,
        "sleep_interval": 0,
        "proxy": None,
        "geo_bypass": False,
        "cookies_file": None,
        "cookies_from_browser": None,
    }

    if not json_path.exists():
        json_path.write_text(json.dumps(default_json, indent=2), encoding="utf-8")

    default_env = """# Universal Media Downloader Environment Configuration
DOWNLOAD_DIR=downloads
LOG_DIR=logs
RETRIES=3
TIMEOUT=30
QUALITY=best
AUDIO_ONLY=false
AUDIO_FORMAT=mp3
AUDIO_QUALITY=192k
WRITE_METADATA=true
EMBED_METADATA=false
EMBED_THUMBNAIL=false
# PROXY=http://127.0.0.1:8080
# COOKIES_FROM_BROWSER=chrome
"""
    if not env_path.exists():
        env_path.write_text(default_env, encoding="utf-8")

    return json_path, env_path
