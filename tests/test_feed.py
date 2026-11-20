import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from universal_downloader.feed import generate_podcast_rss, export_subscription_feed


def test_generate_podcast_rss():
    channel = {
        "title": "My Awesome Channel",
        "url": "https://www.youtube.com/@AwesomeChannel",
        "description": "Tech discussions & coding tutorials",
        "author": "Tech Creator",
        "image": "https://example.com/cover.jpg",
    }
    items = [
        {
            "id": "ep1",
            "title": "Episode 1: Introduction",
            "url": "https://www.youtube.com/watch?v=ep1",
            "duration": 360,
            "uploader": "Tech Creator",
            "media_url": "https://example.com/media/ep1.mp3",
            "mime_type": "audio/mpeg",
        },
        {
            "id": "ep2",
            "title": "Episode 2: Deep Dive",
            "url": "https://www.youtube.com/watch?v=ep2",
            "duration": 720,
            "uploader": "Tech Creator",
            "media_url": "https://example.com/media/ep2.mp4",
            "mime_type": "video/mp4",
        },
    ]

    xml = generate_podcast_rss(channel, items)
    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
    assert "<title>My Awesome Channel</title>" in xml
    assert '<itunes:image href="https://example.com/cover.jpg"/>' in xml
    assert "<title>Episode 1: Introduction</title>" in xml
    assert 'type="audio/mpeg"' in xml
    assert "<title>Episode 2: Deep Dive</title>" in xml
    assert 'type="video/mp4"' in xml

    # Verify XML validity
    root = ET.fromstring(xml)
    channel_el = root.find("channel")
    assert channel_el is not None
    assert channel_el.find("title").text == "My Awesome Channel"
    item_nodes = channel_el.findall("item")
    assert len(item_nodes) == 2


def test_export_subscription_feed(tmp_path):
    channel = {"title": "Test Feed", "url": "https://example.com"}
    test_file = tmp_path / "audio.mp3"
    test_file.write_text("dummy audio data")

    items = [
        {
            "title": "Local Episode",
            "file_path": str(test_file),
            "duration": 180,
        }
    ]

    out_file = tmp_path / "test_feed.xml"
    exported = export_subscription_feed(channel, items, out_file, base_url="http://192.168.1.10:8000")

    assert exported.is_file()
    content = exported.read_text(encoding="utf-8")
    assert "http://192.168.1.10:8000/audio.mp3" in content
    assert 'type="audio/mpeg"' in content
