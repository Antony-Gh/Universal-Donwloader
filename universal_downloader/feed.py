"""Podcast RSS Feed Generator for Subscriptions.

Generates standard RSS 2.0 feeds with iTunes extensions (RFC 822 pubDate,
enclosures, durations, channel art) compatible with AntennaPod, Pocket Casts,
Apple Podcasts, and VLC.
"""

from __future__ import annotations

import datetime
from email.utils import formatdate
import html
import mimetypes
from pathlib import Path
from typing import Any, List, Optional
import xml.etree.ElementTree as ET


def _format_rfc822(dt: Optional[datetime.datetime] = None) -> str:
    """Format datetime into RFC 822 format required by RSS 2.0."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return formatdate(float(dt.timestamp()), usegmt=True)


def _guess_mime_type(filename_or_url: str) -> str:
    """Detect appropriate audio/video MIME type for enclosure tag."""
    lower = filename_or_url.lower()
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".m4a") or lower.endswith(".aac"):
        return "audio/mp4"
    if lower.endswith(".flac"):
        return "audio/flac"
    if lower.endswith(".ogg") or lower.endswith(".opus"):
        return "audio/ogg"
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".mkv"):
        return "video/x-matroska"
    if lower.endswith(".webm"):
        return "video/webm"
    guessed, _ = mimetypes.guess_type(filename_or_url)
    return guessed or "audio/mpeg"


def generate_podcast_rss(
    channel_info: dict[str, Any],
    items: List[dict[str, Any]],
    *,
    base_url: str = "",
) -> str:
    """Generate RSS 2.0 podcast XML from channel metadata and downloaded items."""
    title = html.escape(channel_info.get("title") or channel_info.get("label") or "Universal Downloader Podcast Feed")
    link = html.escape(channel_info.get("link") or channel_info.get("url") or "https://github.com/Antony-Gh/Universal-Donwloader")
    description = html.escape(channel_info.get("description") or f"Offline podcast and media feed generated for {title}")
    author = html.escape(channel_info.get("author") or channel_info.get("uploader") or "Universal Media Downloader")
    image_url = channel_info.get("image") or channel_info.get("thumbnail") or ""
    language = channel_info.get("language") or "en-us"

    pub_date = _format_rfc822()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "  <channel>",
        f"    <title>{title}</title>",
        f"    <link>{link}</link>",
        f"    <description>{description}</description>",
        f"    <language>{language}</language>",
        f"    <lastBuildDate>{pub_date}</lastBuildDate>",
        f"    <itunes:author>{author}</itunes:author>",
        "    <itunes:explicit>false</itunes:explicit>",
        '    <itunes:category text="Technology"/>',
    ]

    if image_url:
        lines.append(f'    <itunes:image href="{html.escape(image_url)}"/>')

    clean_base = base_url.rstrip("/") if base_url else ""

    for item in items:
        it_title = html.escape(item.get("title") or "Episode")
        it_link = html.escape(item.get("url") or link)
        it_desc = html.escape(item.get("description") or it_title)
        it_guid = html.escape(item.get("id") or item.get("guid") or it_link)
        it_author = html.escape(item.get("uploader") or author)
        duration_sec = int(item.get("duration") or 0)

        # Enclosure URL and length
        file_path_str = str(item.get("file_path") or "")
        file_path = Path(file_path_str) if file_path_str else None
        filesize = item.get("filesize") or (file_path.stat().st_size if file_path and file_path.is_file() else 1048576)

        if clean_base and file_path:
            enclosure_url = f"{clean_base}/{html.escape(file_path.name)}"
        elif file_path:
            enclosure_url = file_path.as_uri()
        else:
            enclosure_url = html.escape(item.get("media_url") or it_link)

        mime = item.get("mime_type") or _guess_mime_type(file_path.name if file_path else enclosure_url)

        item_date = item.get("date")
        if isinstance(item_date, datetime.datetime):
            item_pub = _format_rfc822(item_date)
        else:
            item_pub = pub_date

        lines.extend([
            "    <item>",
            f"      <title>{it_title}</title>",
            f"      <link>{it_link}</link>",
            f'      <guid isPermaLink="false">{it_guid}</guid>',
            f"      <pubDate>{item_pub}</pubDate>",
            f"      <description>{it_desc}</description>",
            f'      <enclosure url="{enclosure_url}" length="{filesize}" type="{mime}"/>',
            f"      <itunes:duration>{duration_sec}</itunes:duration>",
            f"      <itunes:author>{it_author}</itunes:author>",
            "      <itunes:explicit>false</itunes:explicit>",
            "    </item>",
        ])

    lines.extend([
        "  </channel>",
        "</rss>",
    ])

    return "\n".join(lines)


def export_subscription_feed(
    subscription: dict[str, Any],
    items: List[dict[str, Any]],
    output_path: Path | str,
    *,
    base_url: str = "",
) -> Path:
    """Generate and write a podcast RSS feed file to the specified path."""
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    xml_content = generate_podcast_rss(subscription, items, base_url=base_url)
    dest.write_text(xml_content, encoding="utf-8")
    return dest
