"""Tests for universal_downloader.native_host (Browser Native Messaging Host)."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.models import AppConfig, DownloadResult
from universal_downloader.native_host import (
    HOST_NAME,
    build_native_host_manifest,
    handle_native_command,
    read_native_message,
    run_native_host,
    write_native_message,
)


def test_read_write_native_message_roundtrip() -> None:
    buf = io.BytesIO()
    payload = {"action": "ping", "id": 42, "unicode": "موسيقى"}
    write_native_message(payload, buf)

    buf.seek(0)
    decoded = read_native_message(buf)
    assert decoded == payload
    # Second read at EOF returns None
    assert read_native_message(buf) is None


def test_read_native_message_rejects_oversized_frame() -> None:
    buf = io.BytesIO(struct.pack("<I", 50 * 1024 * 1024))
    with pytest.raises(ValueError, match="exceeds maximum size"):
        read_native_message(buf)


def test_handle_native_command_ping() -> None:
    reply = handle_native_command({"action": "ping"}, AppConfig())
    assert reply["ok"] is True
    assert reply["host"] == HOST_NAME
    assert "version" in reply


def test_handle_native_command_unknown_and_missing_fields() -> None:
    cfg = AppConfig()
    assert handle_native_command({"action": "bogus"}, cfg)["ok"] is False
    assert handle_native_command({"action": "download"}, cfg)["ok"] is False
    assert handle_native_command({"action": "search"}, cfg)["ok"] is False


def test_handle_native_command_download_mocked(tmp_path: Path) -> None:
    fake_file = tmp_path / "video.mp4"
    fake_file.write_bytes(b"mp4")

    mock_engine = MagicMock()
    mock_engine.download.return_value = DownloadResult(
        success=True,
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        files=[fake_file],
        metadata={"title": "Test Video"},
    )

    reply = handle_native_command(
        {
            "action": "download",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "audio_only": True,
            "quality": "audio",
        },
        AppConfig(output_dir=tmp_path),
        engine_factory=lambda _cfg: mock_engine,
    )
    assert reply["ok"] is True
    assert reply["title"] == "Test Video"
    assert reply["files"] == [str(fake_file)]


@patch("universal_downloader.native_host.search_youtube")
def test_handle_native_command_search(mock_search: MagicMock) -> None:
    mock_search.return_value = [{"id": "abc", "title": "Song"}]
    reply = handle_native_command({"action": "search", "query": "test song", "limit": 3}, AppConfig())
    assert reply["ok"] is True
    assert reply["results"] == [{"id": "abc", "title": "Song"}]


def test_run_native_host_event_loop() -> None:
    in_buf = io.BytesIO()
    out_buf = io.BytesIO()

    write_native_message({"id": "req-1", "action": "ping"}, in_buf)
    in_buf.seek(0)

    exit_code = run_native_host(AppConfig(), in_stream=in_buf, out_stream=out_buf)
    assert exit_code == 0

    out_buf.seek(0)
    resp = read_native_message(out_buf)
    assert resp is not None
    assert resp["ok"] is True
    assert resp["id"] == "req-1"


def test_build_native_host_manifest_chrome_and_firefox() -> None:
    host = Path("/usr/local/bin/universal_downloader_host.sh")
    chrome = build_native_host_manifest(host, browser="chrome")
    assert chrome["name"] == HOST_NAME
    assert chrome["type"] == "stdio"
    assert "allowed_origins" in chrome
    assert "allowed_extensions" not in chrome

    firefox = build_native_host_manifest(host, browser="firefox")
    assert firefox["name"] == HOST_NAME
    assert "allowed_extensions" in firefox
    assert "allowed_origins" not in firefox
