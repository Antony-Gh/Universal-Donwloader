"""Tests for CLI options, batch readers, profile inputs, and engine behavior."""

import argparse
import tempfile
from pathlib import Path
import pytest

import downloader
from universal_downloader.batch import read_batch_file
from universal_downloader.cli import (
    _build_playlist_entries,
    _extract_supported_qualities,
    validate_url_option,
)
from universal_downloader.engine import DownloadEngine
from universal_downloader.exceptions import ConfigurationError, ProfileError
from universal_downloader.extractor import parse_rate_limit
from universal_downloader.models import AppConfig, ContentType, DetectedTarget, Platform
from universal_downloader.profile import resolve_profile_input


def test_validate_url_option():
    # Only positional
    args1 = argparse.Namespace(url="https://youtube.com/watch?v=1", url_option=None)
    assert validate_url_option(args1) == "https://youtube.com/watch?v=1"

    # Only flag
    args2 = argparse.Namespace(url=None, url_option="https://youtube.com/watch?v=2")
    assert validate_url_option(args2) == "https://youtube.com/watch?v=2"

    # Both -> must raise ConfigurationError
    args3 = argparse.Namespace(url="https://youtube.com/watch?v=1", url_option="https://youtube.com/watch?v=2")
    with pytest.raises(ConfigurationError):
        validate_url_option(args3)


def test_read_batch_file():
    with tempfile.TemporaryDirectory() as td:
        batch_path = Path(td) / "urls.txt"
        batch_path.write_text(
            """
            # Comments should be ignored
            https://youtube.com/watch?v=1
            https://instagram.com/p/2/

            https://tiktok.com/@user/video/3
            """,
            encoding="utf-8",
        )
        urls = read_batch_file(batch_path)
        assert len(urls) == 3
        assert urls[0] == "https://youtube.com/watch?v=1"
        assert urls[1] == "https://instagram.com/p/2/"
        assert urls[2] == "https://tiktok.com/@user/video/3"


def test_resolve_profile_input():
    # Standard URL
    assert resolve_profile_input("https://instagram.com/testuser/") == "https://instagram.com/testuser/"

    # platform:username syntax
    assert resolve_profile_input("instagram:john_doe") == "https://instagram.com/john_doe/"
    assert resolve_profile_input("tiktok:@dancer") == "https://tiktok.com/dancer/"
    assert resolve_profile_input("x:techlead") == "https://x.com/techlead/"
    assert resolve_profile_input("youtube:CreatorStudio") == "https://youtube.com/@CreatorStudio"

    # Ambiguous bare @username must raise error
    with pytest.raises(ProfileError, match="ambiguous"):
        resolve_profile_input("@dancer")


def test_parse_rate_limit():
    assert parse_rate_limit("5M") == 5 * 1024 * 1024
    assert parse_rate_limit("500K") == 500 * 1024
    assert parse_rate_limit("1G") == 1024 ** 3
    assert parse_rate_limit("1024") == 1024
    assert parse_rate_limit(None) is None
    assert parse_rate_limit("invalid") is None


def test_choose_output_template():
    with tempfile.TemporaryDirectory() as td:
        cfg = AppConfig(output_dir=Path(td))
        engine = DownloadEngine(cfg)

        target_video = DetectedTarget(
            original_url="https://youtube.com/watch?v=1",
            normalized_url="https://youtube.com/watch?v=1",
            platform=Platform.YOUTUBE,
            content_type=ContentType.VIDEO,
        )
        tmpl = engine.choose_output_template(target_video)
        assert "%(title)" in tmpl
        assert "%(id)s" in tmpl

        target_playlist = DetectedTarget(
            original_url="https://youtube.com/playlist?list=1",
            normalized_url="https://youtube.com/playlist?list=1",
            platform=Platform.YOUTUBE,
            content_type=ContentType.PLAYLIST,
        )
        tmpl_pl = engine.choose_output_template(target_playlist)
        assert "%(playlist_title)s" in tmpl_pl


def test_backward_compatibility_exports():
    # Ensure all primary symbols are exported on downloader module directly
    assert hasattr(downloader, "DownloadEngine")
    assert hasattr(downloader, "AppConfig")
    assert hasattr(downloader, "Platform")
    assert hasattr(downloader, "sanitize_filename")
    assert hasattr(downloader, "normalize_url")
    assert hasattr(downloader, "main")


def test_build_playlist_entries_skips_private_and_builds_youtube_urls():
    raw = [
        {"id": "PmZdQ4MiqwQ", "title": "First Video", "duration": 215, "uploader": "Creator A"},
        {"id": "deleted1234", "title": "[Private video]", "duration": None},
        {
            "id": "vXL-E4JLPj8",
            "url": "https://www.youtube.com/watch?v=vXL-E4JLPj8",
            "title": "Second Video",
            "duration": 90,
            "thumbnails": [{"url": "https://example.com/small.jpg"}, {"url": "https://example.com/large.jpg"}],
        },
    ]
    entries = _build_playlist_entries(raw, Platform.YOUTUBE, "Fallback Creator")
    assert len(entries) == 2
    assert entries[0]["index"] == 1
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=PmZdQ4MiqwQ"
    assert entries[0]["thumbnail"] == "https://i.ytimg.com/vi/PmZdQ4MiqwQ/hqdefault.jpg"
    assert entries[0]["uploader"] == "Creator A"
    assert entries[1]["index"] == 2
    assert entries[1]["thumbnail"] == "https://example.com/large.jpg"
    assert entries[1]["uploader"] == "Fallback Creator"


def test_extract_supported_qualities_sorts_descending_and_includes_audio():
    info = {
        "formats": [
            {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080, "ext": "mp4"},
            {"format_id": "248", "vcodec": "vp9", "acodec": "none", "height": 1080, "ext": "webm"},
            {"format_id": "22", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "ext": "mp4"},
            {"format_id": "135", "vcodec": "avc1", "acodec": "none", "height": 480, "ext": "mp4"},
            {"format_id": "sb0", "vcodec": "none", "acodec": "none", "height": 45, "ext": "mhtml"},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "ext": "m4a"},
        ]
    }
    assert _extract_supported_qualities(info) == ["1080p", "720p", "480p", "Audio"]
