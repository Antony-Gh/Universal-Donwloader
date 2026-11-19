"""Generic webpage media sniffer and harvester.

Scans arbitrary webpage HTML for embedded HTML5 <video>/<audio>/<source> tags,
OpenGraph / Twitter media meta tags, JSON-LD contentUrl entries, and direct
HLS (.m3u8), DASH (.mpd), or progressive media links.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Optional

from universal_downloader.exceptions import ExtractionError

LOGGER = logging.getLogger("universal_downloader")

MAX_HTML_BYTES = 5 * 1024 * 1024  # 5 MB guard
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_STREAM_URL_RE = re.compile(
    r"""(?P<url>https?:\\?/\\?/[^\s"'<>\\)]+?\.(?:m3u8|mpd|mp4|webm|m4v|mov|mp3|m4a|aac|ogg|opus|flac)(?:\?[^\s"'<>\\)]*)?)""",
    re.IGNORECASE,
)

_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
_VIDEO_EXTS = {".mp4", ".webm", ".m4v", ".mov", ".mkv", ".ts"}


@dataclass(frozen=True)
class SniffedMedia:
    url: str
    media_type: str  # "hls", "dash", "video", "audio"
    source: str
    mime_type: Optional[str] = None
    title: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_media_type(url: str, mime_type: Optional[str] = None, default: str = "video") -> str:
    lower_url = url.lower().split("?", 1)[0].split("#", 1)[0]
    lower_mime = (mime_type or "").lower()

    if lower_url.endswith(".m3u8") or "mpegurl" in lower_mime:
        return "hls"
    if lower_url.endswith(".mpd") or "dash+xml" in lower_mime:
        return "dash"
    if any(lower_url.endswith(ext) for ext in _AUDIO_EXTS) or lower_mime.startswith("audio/"):
        return "audio"
    if any(lower_url.endswith(ext) for ext in _VIDEO_EXTS) or lower_mime.startswith("video/"):
        return "video"
    return default


def _normalize_candidate_url(raw_url: str, base_url: str) -> Optional[str]:
    cleaned = html.unescape((raw_url or "").strip()).replace("\\/", "/")
    if not cleaned:
        return None
    lower = cleaned.lower()
    if lower.startswith(("blob:", "data:", "javascript:", "mailto:", "#")):
        return None
    resolved = urllib.parse.urljoin(base_url, cleaned)
    parsed = urllib.parse.urlparse(resolved)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return resolved


class _MediaHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.page_title: Optional[str] = None
        self._in_title = False
        self._in_json_ld = False
        self._json_ld_chunks: list[str] = []
        self._tag_stack: list[str] = []
        self.candidates: list[tuple[str, str, str, Optional[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        self._tag_stack.append(tag_l)

        if tag_l == "title":
            self._in_title = True
        elif tag_l == "script" and "ld+json" in attr_map.get("type", "").lower():
            self._in_json_ld = True
            self._json_ld_chunks = []
        elif tag_l == "video":
            src = attr_map.get("src") or attr_map.get("data-src") or ""
            if src:
                self.candidates.append((src, "video", "html_video", attr_map.get("type") or None))
        elif tag_l == "audio":
            src = attr_map.get("src") or attr_map.get("data-src") or ""
            if src:
                self.candidates.append((src, "audio", "html_audio", attr_map.get("type") or None))
        elif tag_l == "source":
            src = attr_map.get("src") or attr_map.get("data-src") or ""
            mime = attr_map.get("type") or None
            parent = self._tag_stack[-2] if len(self._tag_stack) >= 2 else ""
            default_type = "audio" if parent == "audio" else "video"
            if src:
                self.candidates.append((src, default_type, "html_source", mime))
        elif tag_l == "meta":
            prop = (attr_map.get("property") or attr_map.get("name") or "").lower()
            content = attr_map.get("content") or ""
            if not content:
                return
            if prop in {"og:video", "og:video:url", "og:video:secure_url"}:
                self.candidates.append((content, "video", "opengraph", None))
            elif prop in {"og:audio", "og:audio:url", "og:audio:secure_url"}:
                self.candidates.append((content, "audio", "opengraph", None))
            elif prop == "twitter:player:stream":
                self.candidates.append((content, "video", "twitter_card", None))

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "title":
            self._in_title = False
        elif tag_l == "script" and self._in_json_ld:
            self._in_json_ld = False
            raw_json = "".join(self._json_ld_chunks).strip()
            self._extract_json_ld(raw_json)
            self._json_ld_chunks = []
        if self._tag_stack and self._tag_stack[-1] == tag_l:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.page_title:
            text = data.strip()
            if text:
                self.page_title = text
        elif self._in_json_ld:
            self._json_ld_chunks.append(data)

    def _extract_json_ld(self, raw_json: str) -> None:
        if not raw_json:
            return
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError:
            return

        def _walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    _walk(item)
            elif isinstance(node, dict):
                node_type = str(node.get("@type") or "").lower()
                default_type = "audio" if "audio" in node_type or "podcast" in node_type else "video"
                content_url = node.get("contentUrl")
                if isinstance(content_url, str) and content_url.strip():
                    self.candidates.append((content_url.strip(), default_type, "json_ld", node.get("encodingFormat")))
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        _walk(value)

        _walk(obj)


def extract_media_from_html(html_text: str, base_url: str) -> list[SniffedMedia]:
    """Parse HTML text and return deduplicated media stream candidates."""
    parser = _MediaHTMLParser(base_url)
    try:
        parser.feed(html_text or "")
        parser.close()
    except Exception as exc:
        LOGGER.debug("HTML parser encountered error while sniffing %s: %s", base_url, exc)

    results: list[SniffedMedia] = []
    seen: set[str] = set()

    def _add(raw_url: str, default_type: str, source: str, mime: Optional[str]) -> None:
        normalized = _normalize_candidate_url(raw_url, base_url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        mtype = _classify_media_type(normalized, mime_type=mime, default=default_type)
        results.append(
            SniffedMedia(
                url=normalized,
                media_type=mtype,
                source=source,
                mime_type=mime,
                title=parser.page_title,
            )
        )

    for raw_url, default_type, source, mime in parser.candidates:
        _add(raw_url, default_type, source, mime)

    unescaped_html = (html_text or "").replace("\\/", "/")
    for match in _STREAM_URL_RE.finditer(unescaped_html):
        _add(match.group("url"), "video", "stream_regex", None)

    return results


def sniff_page_media(
    page_url: str,
    *,
    timeout: int = 20,
    user_agent: Optional[str] = None,
) -> list[SniffedMedia]:
    """Fetch a webpage and sniff embedded video, audio, HLS, and DASH streams."""
    page_url = (page_url or "").strip()
    if not page_url:
        raise ValueError("Page URL is empty.")
    if "://" not in page_url:
        page_url = "https://" + page_url

    request = urllib.request.Request(
        page_url,
        headers={"User-Agent": user_agent or DEFAULT_UA},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl() or page_url
            raw_bytes = response.read(MAX_HTML_BYTES)
    except Exception as exc:
        raise ExtractionError(f"Failed to fetch page for sniffing: {exc}") from exc

    html_text = raw_bytes.decode("utf-8", errors="replace")
    return extract_media_from_html(html_text, final_url)
