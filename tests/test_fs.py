"""Tests for filesystem security, sanitization, and metadata persistence."""

import tempfile
from pathlib import Path
import pytest

from universal_downloader.exceptions import DownloadError
from universal_downloader.models import Platform
from universal_downloader.utils.fs import (
    ensure_inside_directory,
    platform_directory,
    preferred_media_filename,
    safe_json_value,
    sanitize_filename,
    unique_path,
    write_metadata_file,
)


def test_sanitize_filename_basic():
    assert sanitize_filename("hello/world:test*file?") == "hello_world_test_file_"
    assert sanitize_filename("   spaced   name   ") == "spaced name"
    assert sanitize_filename("") == "download"
    assert sanitize_filename("   ") == "download"


def test_sanitize_filename_windows_reserved():
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("nul") == "_nul"
    assert sanitize_filename("com1") == "_com1"
    assert sanitize_filename("lpt9") == "_lpt9"


def test_sanitize_filename_html_unescape():
    assert sanitize_filename("Tom &amp; Jerry &#39;Special&#39;") == "Tom & Jerry 'Special'"


def test_ensure_inside_directory_safe():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        valid_child = base / "media" / "video.mp4"
        resolved = ensure_inside_directory(base, valid_child)
        assert resolved == valid_child.resolve()


def test_ensure_inside_directory_traversal():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        evil_path = base / ".." / "system32" / "evil.exe"
        with pytest.raises(DownloadError):
            ensure_inside_directory(base, evil_path)


def test_unique_path():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.txt"
        assert unique_path(p) == p

        p.write_text("first")
        p2 = unique_path(p)
        assert p2.name == "test (1).txt"

        p2.write_text("second")
        p3 = unique_path(p)
        assert p3.name == "test (2).txt"


def test_platform_directory():
    assert platform_directory(Platform.YOUTUBE) == "youtube"
    assert platform_directory(Platform.TWITTER) == "twitter"
    assert platform_directory(Platform.TIKTOK) == "tiktok"


def test_safe_json_value():
    assert safe_json_value(123) == 123
    assert safe_json_value("text") == "text"
    assert safe_json_value([1, "a"]) == [1, "a"]
    assert safe_json_value({"key": "val"}) == {"key": "val"}


def test_write_metadata_file():
    with tempfile.TemporaryDirectory() as td:
        media_path = Path(td) / "song.mp3"
        media_path.write_text("dummy")
        info = {
            "id": "12345",
            "title": "A Great Song",
            "uploader": "Artist",
        }
        json_file = write_metadata_file(media_path, info, "https://youtube.com/watch?v=12345")
        assert json_file is not None
        assert json_file.exists()
        assert "A Great Song" in json_file.read_text(encoding="utf-8")


def test_preferred_media_filename():
    info = {"id": "vid01", "uploader": "creator", "uploader_id": "c101", "ext": "mp4"}
    assert preferred_media_filename(info) == "creator_c101_vid01.mp4"
