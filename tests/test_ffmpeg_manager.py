"""Tests for ffmpeg_manager: discovery, auto-bootstrap, and graceful degradation."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from universal_downloader.ffmpeg_manager import (
    _candidate_ffmpeg_paths,
    _ensure_in_path,
    find_ffmpeg,
    find_ffprobe,
    get_download_url,
    get_local_bin_dir,
    is_ffmpeg_available,
)
from universal_downloader.models import AppConfig
from universal_downloader.extractor import YTDLPExtractor


def test_get_local_bin_dir():
    bin_dir = get_local_bin_dir()
    assert isinstance(bin_dir, Path)
    assert bin_dir.exists()
    assert "universal" in str(bin_dir).lower()
    assert str(bin_dir).endswith("bin")


def test_candidate_ffmpeg_paths():
    paths = _candidate_ffmpeg_paths()
    assert isinstance(paths, list)
    assert len(paths) > 0
    # Every item must be a Path
    assert all(isinstance(p, Path) for p in paths)


def test_ensure_in_path():
    dummy = Path("C:/DummyFfmpegPath123")
    assert str(dummy) not in os.environ.get("PATH", "")
    _ensure_in_path(dummy)
    assert str(dummy) in os.environ["PATH"]


def test_get_download_url():
    url = get_download_url()
    assert url is not None
    assert "yt-dlp/FFmpeg-Builds" in url
    assert url.startswith("https://")


def test_find_ffmpeg_and_availability():
    # find_ffmpeg returns a Path or None
    res = find_ffmpeg()
    if res is not None:
        assert isinstance(res, Path)
        assert res.exists()
        assert is_ffmpeg_available() is True


def test_graceful_fallback_without_ffmpeg():
    """Verify that when FFmpeg is not installed, download does NOT raise DependencyError."""
    config = AppConfig(
        quality="best",
        audio_only=False,
        embed_metadata=True,
        embed_thumbnail=True,
        embed_subs=True,
        remux_video="mp4",
        split_chapters=True,
    )

    extractor = YTDLPExtractor(config)

    # Mock find_ffmpeg to simulate missing FFmpeg on user machine
    with patch("universal_downloader.extractor.find_ffmpeg", return_value=None), \
         patch("universal_downloader.extractor.ensure_ffmpeg", return_value=None):

        dummy_hook = MagicMock()
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test", "title": "Test Video"}
        extractor.yt_dlp.YoutubeDL = MagicMock(return_value=mock_ydl)
        mock_ydl.__enter__.return_value = mock_ydl

        # Calling download with video selector containing '+' must NOT raise DependencyError
        result = extractor.download(
            url="https://example.com/video",
            output_template="%(title)s.%(ext)s",
            format_selector="bestvideo+bestaudio/best",
            progress_hook=dummy_hook,
        )

        # Inspect the options passed to YoutubeDL
        called_options = extractor.yt_dlp.YoutubeDL.call_args[0][0]
        
        # Verify it fell back to single stream requiring no merge!
        assert called_options["format"] == "best[acodec!=none][vcodec!=none]/best"
        # Verify writethumbnail was set to True since EmbedThumbnail was skipped
        assert called_options["writethumbnail"] is True
        # Verify no ffmpeg-dependent postprocessors were attached that would crash
        postprocessor_keys = [p.get("key") for p in called_options.get("postprocessors", [])]
        assert "FFmpegExtractAudio" not in postprocessor_keys
        assert "FFmpegMetadata" not in postprocessor_keys
        assert "FFmpegVideoRemuxer" not in postprocessor_keys


def test_graceful_audio_fallback_without_ffmpeg():
    """Verify audio download without FFmpeg falls back to raw stream without crashing."""
    config = AppConfig(
        quality="audio",
        audio_only=True,
        audio_format="mp3",
    )

    extractor = YTDLPExtractor(config)

    with patch("universal_downloader.extractor.find_ffmpeg", return_value=None), \
         patch("universal_downloader.extractor.ensure_ffmpeg", return_value=None):

        dummy_hook = MagicMock()
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"id": "test", "title": "Test Audio"}
        extractor.yt_dlp.YoutubeDL = MagicMock(return_value=mock_ydl)
        mock_ydl.__enter__.return_value = mock_ydl

        extractor.download(
            url="https://example.com/audio",
            output_template="%(title)s.%(ext)s",
            format_selector="bestaudio/best",
            progress_hook=dummy_hook,
        )

        called_options = extractor.yt_dlp.YoutubeDL.call_args[0][0]
        assert called_options["format"] == "bestaudio/best"
        postprocessor_keys = [p.get("key") for p in called_options.get("postprocessors", [])]
        assert "FFmpegExtractAudio" not in postprocessor_keys
