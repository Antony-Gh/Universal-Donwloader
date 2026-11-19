from pathlib import Path
import pytest

from universal_downloader.duplicate_detector import (
    extract_media_id_from_url,
    clean_comparable_name,
    find_existing_duplicate,
)
from universal_downloader.history import record_download


def test_extract_media_id_from_url():
    assert extract_media_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_media_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_media_id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_media_id_from_url("https://www.tiktok.com/@user/video/7123456789012345678") == "7123456789012345678"
    assert extract_media_id_from_url("https://x.com/user/status/1850000000000000000") == "1850000000000000000"


def test_clean_comparable_name():
    assert clean_comparable_name("Rick Astley - Never Gonna Give You Up.mp4") == "rick astley never gonna give you up"
    assert clean_comparable_name("Song_Title (Official) [HQ].mp3") == "song title official hq"


def test_find_existing_duplicate_via_history(tmp_path: Path):
    db_file = tmp_path / "downloads.db"
    out_file = tmp_path / "video.mp4"
    out_file.write_bytes(b"downloaded media data")

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    record_download(
        db_file,
        url=url,
        files=[out_file],
        metadata={"title": "Rick Astley - Never Gonna Give You Up", "filesize": 100},
        status="completed",
    )

    dup = find_existing_duplicate(url, output_dir=tmp_path, db_path=db_file)
    assert dup is not None
    assert dup["source"] == "history"
    assert Path(dup["path"]).resolve() == out_file.resolve()
    assert dup["title"] == "Rick Astley - Never Gonna Give You Up"


def test_find_existing_duplicate_via_filesystem_id(tmp_path: Path):
    db_file = tmp_path / "empty.db"
    # Local file with YouTube video ID in name
    media_file = tmp_path / "Awesome Video [dQw4w9WgXcQ].mp4"
    media_file.write_bytes(b"existing file")

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    dup = find_existing_duplicate(url, output_dir=tmp_path, db_path=db_file)
    assert dup is not None
    assert dup["source"] == "filesystem_id"
    assert Path(dup["path"]).resolve() == media_file.resolve()


def test_find_existing_duplicate_not_found(tmp_path: Path):
    db_file = tmp_path / "empty.db"
    dup = find_existing_duplicate("https://www.youtube.com/watch?v=unknown12345", output_dir=tmp_path, db_path=db_file)
    assert dup is None
