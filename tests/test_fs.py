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


def test_clean_title_strips_clickbait_and_emojis():
    from universal_downloader.utils.fs import clean_title

    assert clean_title("Queen - Bohemian Rhapsody [Official Music Video] (4K)") == "Queen - Bohemian Rhapsody"
    assert clean_title("Adele - Hello (Lyrics) 🔥🎵") == "Adele - Hello"
    assert clean_title("Coldplay - Yellow (Official Video) [HD] (1080p)") == "Coldplay - Yellow"
    # Fallback when entire title is clickbait
    assert clean_title("[Official Video]") == "[Official Video]"


def test_rename_with_clean_title(tmp_path):
    from universal_downloader.utils.fs import rename_with_clean_title

    original = tmp_path / "Artist - Song [Official Video] (4K).mp4"
    original.write_bytes(b"data")
    renamed = rename_with_clean_title(original, "Artist - Song [Official Video] (4K)")
    assert renamed.name == "Artist - Song.mp4"
    assert renamed.exists()
    assert not original.exists()


def test_organize_modes_in_choose_output_template(tmp_path):
    from universal_downloader.engine import DownloadEngine
    from universal_downloader.models import AppConfig, ContentType, DetectedTarget

    target = DetectedTarget(
        original_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        normalized_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        platform=Platform.YOUTUBE,
        content_type=ContentType.VIDEO,
    )

    # none (flat)
    eng_none = DownloadEngine(AppConfig(output_dir=tmp_path, organize="none"))
    t_none = eng_none.choose_output_template(target)
    assert str(tmp_path) in t_none
    assert "youtube" not in t_none.lower()

    # platform (default)
    eng_plat = DownloadEngine(AppConfig(output_dir=tmp_path, organize="platform"))
    t_plat = eng_plat.choose_output_template(target)
    assert "youtube" in t_plat.lower()

    # uploader
    eng_up = DownloadEngine(AppConfig(output_dir=tmp_path, organize="uploader"))
    t_up = eng_up.choose_output_template(target)
    assert "%(uploader,channel,uploader_id|Unknown)s" in t_up

    # date
    eng_date = DownloadEngine(AppConfig(output_dir=tmp_path, organize="date"))
    t_date = eng_date.choose_output_template(target)
    assert "%(upload_date>%Y-%m|Undated)s" in t_date
