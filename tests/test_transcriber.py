import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from universal_downloader.transcriber import (
    format_timestamp,
    write_srt,
    write_vtt,
    write_txt,
    summarize_text,
    transcribe_media,
)


def test_format_timestamp():
    # 0 seconds
    assert format_timestamp(0.0, ",") == "00:00:00,000"
    assert format_timestamp(0.0, ".") == "00:00:00.000"

    # 1 hour 23 mins 45.678 secs
    secs = 3600 + 23 * 60 + 45.678
    assert format_timestamp(secs, ",") == "01:23:45,678"
    assert format_timestamp(secs, ".") == "01:23:45.678"


def test_write_srt_and_vtt_and_txt(tmp_path: Path):
    segments = [
        {"start": 0.0, "end": 2.5, "text": "Hello world."},
        {"start": 3.0, "end": 5.2, "text": "This is a test of local Whisper AI."},
    ]

    srt_file = tmp_path / "sub.srt"
    write_srt(segments, srt_file)
    assert srt_file.exists()
    srt_content = srt_file.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:02,500\nHello world." in srt_content
    assert "2\n00:00:03,000 --> 00:00:05,200\nThis is a test of local Whisper AI." in srt_content

    vtt_file = tmp_path / "sub.vtt"
    write_vtt(segments, vtt_file)
    assert vtt_file.exists()
    vtt_content = vtt_file.read_text(encoding="utf-8")
    assert "WEBVTT" in vtt_content
    assert "00:00:00.000 --> 00:00:02.500" in vtt_content

    txt_file = tmp_path / "sub.txt"
    write_txt(segments, txt_file)
    assert txt_file.exists()
    txt_content = txt_file.read_text(encoding="utf-8").strip()
    assert txt_content == "Hello world. This is a test of local Whisper AI."


def test_summarize_text():
    sample_text = (
        "Universal Media Downloader is a high performance cross platform application. "
        "It supports downloading videos, music, and streams from over 1000 websites. "
        "The application provides desktop tray support, smart scheduled downloads, and offline AI transcription. "
        "Users can convert files between formats and extract audio directly. "
        "Privacy and performance are central tenets of the software architecture. "
        "Everything runs locally without cloud dependencies."
    )
    summary = summarize_text(sample_text, max_sentences=3)
    assert summary.startswith("• ")
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    assert len(lines) <= 3
    assert any("Universal Media Downloader" in line or "performance" in line for line in lines)


def test_transcribe_media_missing_file(tmp_path: Path):
    non_existent = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        transcribe_media(non_existent)


def test_transcribe_media_with_mocked_faster_whisper(tmp_path: Path):
    media_file = tmp_path / "sample.mp4"
    media_file.write_bytes(b"dummy video bytes")

    mock_segment = MagicMock()
    mock_segment.start = 1.0
    mock_segment.end = 4.0
    mock_segment.text = "Mocked offline transcribed speech."

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], None)

    mock_fw = MagicMock()
    mock_fw.WhisperModel.return_value = mock_model

    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        results = transcribe_media(
            media_file,
            output_dir=tmp_path,
            model_name="tiny",
            formats=("srt", "vtt", "txt"),
            summarize=True,
        )

        assert "srt" in results
        assert "vtt" in results
        assert "txt" in results
        assert "summary" in results

        assert (tmp_path / "sample.srt").exists()
        assert (tmp_path / "sample.vtt").exists()
        assert (tmp_path / "sample.txt").exists()
        assert (tmp_path / "sample.summary.txt").exists()

        txt_content = (tmp_path / "sample.txt").read_text(encoding="utf-8")
        assert "Mocked offline transcribed speech." in txt_content
