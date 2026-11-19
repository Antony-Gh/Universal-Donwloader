"""Tests for universal_downloader.sniffer (generic webpage media sniffer)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.cli import main
from universal_downloader.sniffer import SniffedMedia, extract_media_from_html, sniff_page_media

SAMPLE_HTML = """<!doctype html>
<html>
<head>
  <title>Sample News Article</title>
  <meta property="og:video" content="https://cdn.example.com/og-clip.mp4" />
  <meta property="og:audio" content="/media/podcast.mp3" />
  <meta name="twitter:player:stream" content="https://cdn.example.com/tw-stream.m3u8?token=abc" />
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    "contentUrl": "https://cdn.example.com/ld-video.webm",
    "encodingFormat": "video/webm"
  }
  </script>
</head>
<body>
  <video src="/clips/intro.mp4">
    <source src="https://cdn.example.com/alt.mp4" type="video/mp4" />
    <source src="blob:https://example.com/ignored-blob" type="video/mp4" />
  </video>
  <audio>
    <source src="data:audio/mp3;base64,AAA" />
    <source src="https://cdn.example.com/theme.m4a" type="audio/mp4" />
  </audio>
  <script>
    var playerConfig = {
      "hls": "https:\\/\\/stream.example.com\\/live\\/master.m3u8?sig=1",
      "dash": "https://stream.example.com/vod/manifest.mpd"
    };
  </script>
</body>
</html>
"""


def test_extract_media_from_html_all_sources() -> None:
    items = extract_media_from_html(SAMPLE_HTML, "https://news.example.com/articles/1")
    by_url = {item.url: item for item in items}

    assert "https://cdn.example.com/og-clip.mp4" in by_url
    assert by_url["https://cdn.example.com/og-clip.mp4"].media_type == "video"
    assert by_url["https://cdn.example.com/og-clip.mp4"].source == "opengraph"
    assert by_url["https://cdn.example.com/og-clip.mp4"].title == "Sample News Article"

    # Relative URL resolved against base_url
    assert "https://news.example.com/media/podcast.mp3" in by_url
    assert by_url["https://news.example.com/media/podcast.mp3"].media_type == "audio"

    assert "https://news.example.com/clips/intro.mp4" in by_url
    assert by_url["https://news.example.com/clips/intro.mp4"].source == "html_video"

    assert "https://cdn.example.com/alt.mp4" in by_url
    assert "https://cdn.example.com/theme.m4a" in by_url
    assert by_url["https://cdn.example.com/theme.m4a"].media_type == "audio"

    assert "https://cdn.example.com/ld-video.webm" in by_url
    assert by_url["https://cdn.example.com/ld-video.webm"].source == "json_ld"

    # Escaped HLS + DASH in inline JS
    assert "https://stream.example.com/live/master.m3u8?sig=1" in by_url
    assert by_url["https://stream.example.com/live/master.m3u8?sig=1"].media_type == "hls"
    assert "https://stream.example.com/vod/manifest.mpd" in by_url
    assert by_url["https://stream.example.com/vod/manifest.mpd"].media_type == "dash"

    # blob: and data: URIs excluded
    assert not any(u.startswith(("blob:", "data:")) for u in by_url)


@patch("urllib.request.urlopen")
def test_sniff_page_media_fetches_and_parses(mock_urlopen: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.geturl.return_value = "https://blog.example.com/post"
    mock_resp.read.return_value = b'<video src="/v.mp4"></video>'
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    found = sniff_page_media("blog.example.com/post")
    assert len(found) == 1
    assert found[0].url == "https://blog.example.com/v.mp4"
    assert found[0].media_type == "video"


@patch("universal_downloader.cli.sniff_page_media")
def test_cli_sniff_json(mock_sniff: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_sniff.return_value = [
        SniffedMedia(
            url="https://cdn.example.com/stream.m3u8",
            media_type="hls",
            source="stream_regex",
            title="Live Page",
        )
    ]

    with patch("sys.argv", ["downloader.py", "--sniff", "https://example.com/live", "--json"]):
        code = main()

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["count"] == 1
    assert data["media"][0]["media_type"] == "hls"
    assert data["media"][0]["url"] == "https://cdn.example.com/stream.m3u8"
