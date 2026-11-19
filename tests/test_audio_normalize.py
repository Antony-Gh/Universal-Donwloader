"""Tests for EBU R128 (-14 LUFS) audio loudness normalization (--normalize-audio)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from universal_downloader.cli import build_parser
from universal_downloader.config import build_config
from universal_downloader.converter import build_ffmpeg_convert_cmd
from universal_downloader.extractor import YTDLPExtractor
from universal_downloader.models import AppConfig


def test_converter_includes_loudnorm_filter_when_normalize_audio_enabled(tmp_path: Path) -> None:
    cmd = build_ffmpeg_convert_cmd(
        Path("ffmpeg"),
        tmp_path / "in.mp4",
        tmp_path / "out.mp3",
        "mp3",
        normalize_audio=True,
    )
    assert "-af" in cmd
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd

    # Lossless container remux (-c copy) should not attach audio filters
    remux_cmd = build_ffmpeg_convert_cmd(
        Path("ffmpeg"),
        tmp_path / "in.mkv",
        tmp_path / "out.mp4",
        "mp4",
        remux_only=True,
        normalize_audio=True,
    )
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" not in remux_cmd


def test_extractor_sets_ffmpeg_postprocessor_args_for_normalize_audio() -> None:
    captured_opts: dict = {}

    class _DummyYDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            return {"title": "Normalized Track", "_filename": "track.mp3"}

    dummy_mod = MagicMock()
    dummy_mod.YoutubeDL = _DummyYDL

    cfg = AppConfig(audio_only=True, normalize_audio=True)
    with patch("universal_downloader.extractor.import_yt_dlp", return_value=dummy_mod), patch(
        "universal_downloader.extractor.find_ffmpeg", return_value=Path("/usr/bin/ffmpeg")
    ):
        extractor = YTDLPExtractor(cfg)
        extractor.download(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "%(title)s.%(ext)s",
            "bestaudio/best",
            lambda _d: None,
        )

    assert "postprocessor_args" in captured_opts
    assert captured_opts["postprocessor_args"]["ffmpeg"] == ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]


def test_cli_parses_normalize_audio_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--audio-only", "--normalize-audio", "https://youtu.be/dQw4w9WgXcQ"])
    cfg = build_config(args)
    assert cfg.normalize_audio is True
