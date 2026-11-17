"""Tests for configuration ingestion and validation."""

import argparse
import json
import tempfile
from pathlib import Path
import pytest

from universal_downloader.config import (
    build_config,
    load_json_config,
    parse_config_bool,
    parse_config_int,
    parse_dotenv,
)
from universal_downloader.exceptions import ConfigurationError


def test_parse_dotenv():
    with tempfile.TemporaryDirectory() as td:
        env_file = Path(td) / ".env"
        env_file.write_text(
            """
            # Comments should be ignored
            DOWNLOAD_DIR=/custom/downloads
            QUALITY="1080p"
            AUDIO_ONLY='true'
            RETRIES=5
            export EXPORTED=val
            INVALID_LINE_WITHOUT_EQUALS
            """,
            encoding="utf-8",
        )
        parsed = parse_dotenv(env_file)
        assert parsed["DOWNLOAD_DIR"] == "/custom/downloads"
        assert parsed["QUALITY"] == "1080p"
        assert parsed["AUDIO_ONLY"] == "true"
        assert parsed["RETRIES"] == "5"
        assert parsed["EXPORTED"] == "val"


def test_load_json_config():
    with tempfile.TemporaryDirectory() as td:
        cfg_file = Path(td) / "config.json"
        cfg_file.write_text(json.dumps({"retries": 4, "quality": "720p"}))
        cfg = load_json_config(cfg_file)
        assert cfg["retries"] == 4
        assert cfg["quality"] == "720p"


def test_parse_config_helpers():
    assert parse_config_int("10", "test", 1) == 10
    assert parse_config_int(None, "test", 5) == 5
    with pytest.raises(ConfigurationError):
        parse_config_int("not-an-int", "test", 1)

    assert parse_config_bool("true") is True
    assert parse_config_bool("1") is True
    assert parse_config_bool("false") is False
    assert parse_config_bool(None, default=True) is True


def test_build_config_cli_precedence():
    args = argparse.Namespace(
        output="my_downloads",
        retries=2,
        timeout=15,
        quality="480p",
        audio_only=True,
        audio_format="flac",
        audio_quality="320k",
        no_metadata=False,
        embed_metadata=True,
        embed_thumbnail=True,
        write_subs=True,
        embed_subs=False,
        sub_langs="en",
        auto_subs=False,
        output_template="%(title)s.%(ext)s",
        download_archive=None,
        concurrency=4,
        limit_rate="2M",
        sleep_interval=2,
        max_sleep_interval=5,
        proxy="http://proxy:8080",
        geo_bypass=True,
        sponsorblock_remove=None,
        split_chapters=False,
        remux_video="mp4",
        playlist_items=None,
        max_downloads=10,
        cookies=None,
        cookies_from_browser=None,
        dry_run=True,
        json_output=True,
        verbose=True,
        debug=False,
        no_color=False,
    )
    config = build_config(args)
    assert config.output_dir == Path("my_downloads")
    assert config.retries == 2
    assert config.audio_only is True
    assert config.audio_format == "flac"
    assert config.audio_quality == "320k"
    assert config.embed_metadata is True
    assert config.concurrency == 4
    assert config.limit_rate == "2M"
    assert config.proxy == "http://proxy:8080"
    assert config.dry_run is True
    assert config.json_output is True
