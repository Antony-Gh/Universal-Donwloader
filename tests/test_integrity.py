"""Tests for post-download media integrity verification and SHA-256 checksums."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from universal_downloader.cli import build_parser
from universal_downloader.config import build_config
from universal_downloader.integrity import (
    compute_sha256,
    verify_media_integrity,
    write_sha256_sidecar,
)


def test_compute_sha256_and_write_sidecar(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    payload = b"hello universal downloader integrity test"
    media.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert compute_sha256(media) == expected

    sidecar = write_sha256_sidecar(media)
    assert sidecar.name == "clip.mp4.sha256"
    assert sidecar.read_text(encoding="utf-8") == f"{expected}  clip.mp4\n"


def test_verify_media_integrity_missing_and_empty(tmp_path: Path) -> None:
    ok_missing, msg_missing = verify_media_integrity(tmp_path / "missing.mp4")
    assert ok_missing is False
    assert "does not exist" in msg_missing

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    ok_empty, msg_empty = verify_media_integrity(empty)
    assert ok_empty is False
    assert "0 bytes" in msg_empty


@patch("universal_downloader.integrity.subprocess.run")
def test_verify_media_integrity_with_ffmpeg(mock_run: MagicMock, tmp_path: Path) -> None:
    media = tmp_path / "valid.mp4"
    media.write_bytes(b"mp4-container-bytes")

    proc_ok = MagicMock()
    proc_ok.returncode = 0
    proc_ok.stderr = ""
    mock_run.return_value = proc_ok

    ok, msg = verify_media_integrity(media, ffmpeg_path=Path("ffmpeg"))
    assert ok is True
    assert "verified" in msg.lower()

    # Corrupt container failure
    proc_fail = MagicMock()
    proc_fail.returncode = 1
    proc_fail.stderr = "moov atom not found"
    proc_fail.stdout = ""
    mock_run.return_value = proc_fail

    ok_bad, msg_bad = verify_media_integrity(media, ffmpeg_path=Path("ffmpeg"))
    assert ok_bad is False
    assert "moov atom not found" in msg_bad


def test_cli_parses_verify_and_write_checksum_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["--verify", "--write-checksum", "https://youtu.be/dQw4w9WgXcQ"])
    cfg = build_config(args)
    assert cfg.verify_integrity is True
    assert cfg.write_checksum is True
