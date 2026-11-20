from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from universal_downloader.backup import backup_media_file, copy_to_network_share, upload_webdav


def test_copy_to_network_share(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_text("dummy video content")

    share_dir = tmp_path / "nas_share"
    dest = copy_to_network_share(source, share_dir)

    assert dest.is_file()
    assert dest.read_text() == "dummy video content"
    assert dest.parent == share_dir


def test_backup_media_file_local_target(tmp_path):
    source = tmp_path / "song.mp3"
    source.write_text("dummy song")

    dest_folder = tmp_path / "smb_backup"
    ok = backup_media_file(source, str(dest_folder))

    assert ok is True
    assert (dest_folder / "song.mp3").is_file()


def test_upload_webdav_mocked(tmp_path):
    source = tmp_path / "doc.pdf"
    source.write_text("dummy pdf")

    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        ok = upload_webdav(source, "https://nextcloud.example.com/webdav/media", username="user", password="secret_password")
        assert ok is True


def test_backup_missing_file(tmp_path):
    ok = backup_media_file(tmp_path / "missing.mp4", str(tmp_path / "target"))
    assert ok is False
