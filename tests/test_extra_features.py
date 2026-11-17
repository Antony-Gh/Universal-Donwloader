"""Tests for new enhancements: slicing, streaming JSON, codec preference, protocol cleaning."""

import json
from io import StringIO
import sys

from universal_downloader.extractor import parse_timestamp_seconds
from universal_downloader.formats import quality_to_selector
from universal_downloader.models import AppConfig
from universal_downloader.progress import ProgressRenderer, emit_json_event
from universal_downloader.protocol import clean_protocol_url
from universal_downloader.updater import get_installed_ytdlp_version


def test_parse_timestamp_seconds():
    assert parse_timestamp_seconds("01:30:15") == 5415.0
    assert parse_timestamp_seconds("03:15") == 195.0
    assert parse_timestamp_seconds("90") == 90.0
    assert parse_timestamp_seconds("*01:10") == 70.0
    assert parse_timestamp_seconds(None) is None
    assert parse_timestamp_seconds("invalid") is None


def test_prefer_codec_selector():
    # H.264
    sel_h264 = quality_to_selector("best", audio_only=False, prefer_codec="h264")
    assert "vcodec^=avc1" in sel_h264

    # VP9
    sel_vp9 = quality_to_selector("1080p", audio_only=False, prefer_codec="vp9")
    assert "vcodec^=vp9" in sel_vp9

    # AV1
    sel_av1 = quality_to_selector("720p", audio_only=False, prefer_codec="av1")
    assert "vcodec^=av01" in sel_av1


def test_clean_protocol_url():
    assert clean_protocol_url("downloader://https://youtube.com/watch?v=123") == "https://youtube.com/watch?v=123"
    assert clean_protocol_url("downloader:https://x.com/status/456") == "https://x.com/status/456"
    assert clean_protocol_url("https://youtube.com/watch?v=123") == "https://youtube.com/watch?v=123"


def test_json_streaming_progress(capsys):
    cfg = AppConfig(json_stream=True)
    renderer = ProgressRenderer(cfg)

    # Trigger downloading hook
    renderer(
        {
            "status": "downloading",
            "downloaded_bytes": 524288,
            "total_bytes": 1048576,
            "speed": 262144,
            "eta": 2,
            "filename": "video.mp4",
        }
    )

    captured = capsys.readouterr().out
    assert captured.strip() != ""
    event = json.loads(captured.strip())
    assert event["event"] == "progress"
    assert event["percent"] == 50.0
    assert event["downloaded_bytes"] == 524288
    assert event["total_bytes"] == 1048576


def test_emit_json_event(capsys):
    emit_json_event("complete", {"url": "https://test.com", "files": ["a.mp4"]})
    captured = capsys.readouterr().out
    data = json.loads(captured.strip())
    assert data["event"] == "complete"
    assert data["files"] == ["a.mp4"]


def test_installed_ytdlp_version():
    ver = get_installed_ytdlp_version()
    assert ver != "not installed"
    assert len(ver) > 0
