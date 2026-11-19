"""Tests for universal_downloader.search (text search and suggestion engine)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.cli import main
from universal_downloader.exceptions import ExtractionError
from universal_downloader.search import (
    _entry_to_result,
    format_duration,
    is_valid_search_query,
    looks_like_url,
    search_youtube,
)


def test_looks_like_url() -> None:
    assert looks_like_url("https://www.youtube.com/watch?v=123") is True
    assert looks_like_url("http://foo.bar") is True
    assert looks_like_url("www.example.com") is True
    assert looks_like_url("file:///c:/path") is True
    assert looks_like_url("queen bohemian rhapsody") is False
    assert looks_like_url("coldplay - yellow") is False


def test_is_valid_search_query() -> None:
    assert is_valid_search_query("queen") is True
    assert is_valid_search_query("adele hello") is True
    assert is_valid_search_query("a" * 2) is True
    assert is_valid_search_query("a" * 64) is True
    # Too short
    assert is_valid_search_query("a") is False
    assert is_valid_search_query("") is False
    # Too long
    assert is_valid_search_query("a" * 65) is False
    # Looks like a URL
    assert is_valid_search_query("https://youtu.be/xyz") is False
    assert is_valid_search_query("www.facebook.com") is False


def test_format_duration() -> None:
    assert format_duration(None) == ""
    assert format_duration(0) == ""
    assert format_duration(-10) == ""
    assert format_duration(45) == "0:45"
    assert format_duration(125) == "2:05"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3665) == "1:01:05"


def test_entry_to_result_valid() -> None:
    entry = {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up",
        "uploader": "RickAstleyVEVO",
        "duration": 212,
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "view_count": 1000000,
    }
    res = _entry_to_result(entry)
    assert res is not None
    assert res["id"] == "dQw4w9WgXcQ"
    assert res["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert res["title"] == "Rick Astley - Never Gonna Give You Up"
    assert res["uploader"] == "RickAstleyVEVO"
    assert res["duration_string"] == "3:32"
    assert res["source"] == "YouTube"


def test_entry_to_result_filtered() -> None:
    # Deleted / unavailable video
    assert _entry_to_result({"id": "abc", "title": "[Deleted video]"}) is None
    assert _entry_to_result({"id": "abc", "title": "[Private video]"}) is None
    # No ID or webpage_url
    assert _entry_to_result({"title": "Some Song"}) is None


@patch("yt_dlp.YoutubeDL")
def test_search_youtube_mocked(mock_ydl_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance
    mock_instance.extract_info.return_value = {
        "entries": [
            {
                "id": "vid1",
                "title": "Song One",
                "channel": "Artist A",
                "duration": 180,
                "thumbnail": "https://img.com/1.jpg",
            },
            {
                "id": "vid1",  # duplicate, should be deduplicated
                "title": "Song One",
            },
            {
                "id": "vid2",
                "title": "Song Two",
                "uploader": "Artist B",
                "duration": 240,
            },
        ]
    }

    results = search_youtube("artist a", limit=5)
    assert len(results) == 2
    assert results[0]["id"] == "vid1"
    assert results[0]["title"] == "Song One"
    assert results[0]["duration_string"] == "3:00"
    assert results[1]["id"] == "vid2"


def test_search_youtube_invalid_query() -> None:
    with pytest.raises(ValueError, match="Search text must be"):
        search_youtube("x")


@patch("universal_downloader.cli.search_youtube")
def test_cli_search_json(mock_search: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_search.return_value = [
        {
            "id": "vid123",
            "url": "https://www.youtube.com/watch?v=vid123",
            "title": "Search Result Title",
            "uploader": "Channel Name",
            "duration_string": "4:15",
            "thumbnail": "https://thumb.jpg",
        }
    ]

    with patch("sys.argv", ["downloader.py", "--search", "test query", "--json"]):
        code = main()

    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["success"] is True
    assert data["query"] == "test query"
    assert len(data["results"]) == 1
    assert data["results"][0]["id"] == "vid123"
