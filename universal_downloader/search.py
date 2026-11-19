"""Text search (YouTube) and query autosuggest helpers.

Inspired by the search-first workflow of music-downloader sites: the user can type a song or
video name instead of pasting a link, pick a result, and download it with the normal engine.
Everything runs locally through yt-dlp's ``ytsearch`` extractor - no third-party APIs or keys.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

from universal_downloader.exceptions import ExtractionError
from universal_downloader.utils.net import extract_youtube_video_id

LOGGER = logging.getLogger("universal_downloader")

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 64
DEFAULT_RESULT_LIMIT = 10
MAX_RESULT_LIMIT = 25

SUGGEST_ENDPOINT = "https://suggestqueries-clients6.youtube.com/complete/search"
SUGGEST_LIMIT = 8

# A query that looks like a link/domain is not a text search.
_URLISH_RE = re.compile(r"(https?://|file:///|www\.|\.com|\.net|\.org)", re.IGNORECASE)


def looks_like_url(value: str) -> bool:
    return bool(_URLISH_RE.search(value or ""))


def is_valid_search_query(query: str) -> bool:
    """True when ``query`` is a plain-text search (2-64 chars, not a URL)."""
    query = (query or "").strip()
    return MIN_QUERY_LENGTH <= len(query) <= MAX_QUERY_LENGTH and not looks_like_url(query)


def format_duration(seconds: Optional[float]) -> str:
    if not seconds or seconds <= 0:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _entry_to_result(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    video_id = str(entry.get("id") or "").strip()
    url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    if not video_id:
        video_id = extract_youtube_video_id(url) or ""
    if not video_id:
        return None

    title = (entry.get("title") or "").strip()
    if not title or title.lower() in {"[private video]", "[deleted video]", "[unavailable video]"}:
        return None

    duration = entry.get("duration")
    thumbnail = entry.get("thumbnail")
    if not thumbnail:
        thumbs = entry.get("thumbnails") or []
        if thumbs and isinstance(thumbs[-1], dict):
            thumbnail = thumbs[-1].get("url")
    if not thumbnail:
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "uploader": entry.get("uploader") or entry.get("channel") or entry.get("uploader_id") or "",
        "duration": duration,
        "duration_string": entry.get("duration_string") or format_duration(duration),
        "thumbnail": thumbnail,
        "view_count": entry.get("view_count"),
        "source": "YouTube",
    }


def search_youtube(
    query: str,
    limit: int = DEFAULT_RESULT_LIMIT,
    *,
    timeout: int = 20,
    proxy: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Search YouTube through yt-dlp and return normalised result dictionaries."""
    query = (query or "").strip()
    if not is_valid_search_query(query):
        raise ValueError(
            f"Search text must be {MIN_QUERY_LENGTH}-{MAX_QUERY_LENGTH} characters and must not be a link."
        )

    limit = max(1, min(int(limit or DEFAULT_RESULT_LIMIT), MAX_RESULT_LIMIT))

    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ExtractionError("yt-dlp is not installed.") from exc

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "socket_timeout": timeout,
        "noprogress": True,
    }
    if proxy:
        options["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        LOGGER.debug("YouTube search failed: %s", exc)
        raise ExtractionError(f"Search failed: {exc}") from exc

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in (info or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        result = _entry_to_result(entry)
        if result and result["id"] not in seen:
            seen.add(result["id"])
            results.append(result)
    return results


def parse_suggest_payload(payload: str) -> list[str]:
    """Parse YouTube's autosuggest response (JSON or JSONP) into a list of phrases."""
    text = (payload or "").strip()
    if not text:
        return []

    # JSONP: callback([...]) -> extract the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    suggestions: list[str] = []
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        for item in data[1]:
            phrase = item[0] if isinstance(item, list) and item else item
            if isinstance(phrase, str) and phrase.strip() and phrase not in suggestions:
                suggestions.append(phrase.strip())
            if len(suggestions) >= SUGGEST_LIMIT:
                break
    return suggestions


def fetch_suggestions(query: str, *, timeout: int = 5, language: str = "en") -> list[str]:
    """Return up to 8 autosuggest phrases for ``query`` (empty list when not a text query)."""
    query = (query or "").strip()
    if not is_valid_search_query(query):
        return []

    params = urllib.parse.urlencode({"client": "youtube", "ds": "yt", "hl": language, "q": query})
    request = urllib.request.Request(
        f"{SUGGEST_ENDPOINT}?{params}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        LOGGER.debug("Suggestion lookup failed: %s", exc)
        return []
    return parse_suggest_payload(raw)
