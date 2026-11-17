"""Tests for format parsing, sorting, and selector string mapping."""

import pytest

from universal_downloader.exceptions import ConfigurationError
from universal_downloader.formats import (
    parse_format,
    quality_to_selector,
    unique_video_heights,
)


def test_quality_to_selector():
    assert quality_to_selector("best", audio_only=False) == "bestvideo*+bestaudio/best"
    assert quality_to_selector("max", audio_only=False) == "bestvideo*+bestaudio/best"
    assert quality_to_selector("audio", audio_only=False) == "bestaudio/best"
    assert quality_to_selector("1080p", audio_only=False) == (
        "bestvideo*[height<=1080]+bestaudio/best[height<=1080]/best"
    )
    assert quality_to_selector("720p", audio_only=False) == (
        "bestvideo*[height<=720]+bestaudio/best[height<=720]/best"
    )
    assert quality_to_selector("best", audio_only=True) == "bestaudio/best"

    # Explicit yt-dlp selector
    assert quality_to_selector("bv[ext=mp4]+ba[ext=m4a]", audio_only=False) == "bv[ext=mp4]+ba[ext=m4a]"

    with pytest.raises(ConfigurationError):
        quality_to_selector("invalid quality string!@#", audio_only=False)


def test_parse_format_and_heights():
    raw_info = {
        "formats": [
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "width": 640,
                "fps": 30,
                "filesize": 10485760,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "format_note": "medium",
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "width": 1920,
                "fps": 60,
                "filesize": 52428800,
                "vcodec": "avc1",
                "acodec": "none",
                "format_note": "1080p60",
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "height": None,
                "width": None,
                "fps": None,
                "filesize": 5242880,
                "vcodec": "none",
                "acodec": "mp4a",
                "format_note": "audio",
            },
        ]
    }

    formats = parse_format(raw_info)
    assert len(formats) == 3

    assert formats[0].has_video is True
    assert formats[0].has_audio is True

    assert formats[1].has_video is True
    assert formats[1].has_audio is False

    assert formats[2].has_video is False
    assert formats[2].has_audio is True

    heights = unique_video_heights(formats)
    assert heights == [1080, 360]
