"""Tests for live stream recording duration caps (--record-duration / --live-from-start)."""

from __future__ import annotations

import pytest

from universal_downloader.cli import build_parser
from universal_downloader.config import build_config
from universal_downloader.extractor import YTDLPExtractor, parse_duration_seconds
from universal_downloader.models import AppConfig


def test_parse_duration_seconds_formats() -> None:
    assert parse_duration_seconds(None) is None
    assert parse_duration_seconds("") is None
    assert parse_duration_seconds("90") == 90.0
    assert parse_duration_seconds("02:30") == 150.0
    assert parse_duration_seconds("01:05:10") == 3910.0
    assert parse_duration_seconds("5m") == 300.0
    assert parse_duration_seconds("1h30m") == 5400.0
    assert parse_duration_seconds("1h 2m 3s") == 3723.0


def test_parse_duration_seconds_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid record duration"):
        parse_duration_seconds("0")
    with pytest.raises(ValueError, match="Invalid record duration"):
        parse_duration_seconds("-15")
    with pytest.raises(ValueError, match="Invalid record duration"):
        parse_duration_seconds("forever")


def test_extractor_sets_ffmpeg_record_duration_options() -> None:
    from unittest.mock import MagicMock, patch

    captured_opts: dict = {}

    class _DummyYDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            return {"title": "Live Stream", "_filename": "live.mp4"}

    dummy_mod = MagicMock()
    dummy_mod.YoutubeDL = _DummyYDL

    cfg = AppConfig(record_duration="00:05:00", live_from_start=True)
    with patch("universal_downloader.extractor.import_yt_dlp", return_value=dummy_mod):
        extractor = YTDLPExtractor(cfg)
        extractor.download(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "%(title)s.%(ext)s",
            "best",
            lambda _d: None,
        )

    assert captured_opts["live_from_start"] is True
    assert captured_opts["hls_use_mpegts"] is True
    assert captured_opts["external_downloader"] == "ffmpeg"
    assert captured_opts["external_downloader_args"]["ffmpeg"] == ["-t", "300"]


def test_cli_parses_record_duration_and_live_from_start() -> None:
    parser = build_parser()
    args = parser.parse_args(["--record-duration", "10m", "--live-from-start", "https://twitch.tv/channel"])
    cfg = build_config(args)
    assert cfg.record_duration == "10m"
    assert cfg.live_from_start is True
