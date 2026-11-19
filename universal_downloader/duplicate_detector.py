"""Intelligent pre-download duplicate detection checking history database and local storage."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

from universal_downloader.history import get_db_path, init_db

LOGGER = logging.getLogger("universal_downloader.duplicate_detector")


def extract_media_id_from_url(url: str) -> Optional[str]:
    """Extract standard video/post identifier from common platform URLs."""
    if not url:
        return None

    try:
        parsed = urllib.parse.urlparse(url)
        # YouTube: v=ID or /shorts/ID or /live/ID or youtu.be/ID
        if "youtube.com" in parsed.netloc:
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]
            m = re.search(r"/(?:shorts|live|embed)/([a-zA-Z0-9_-]{11})", parsed.path)
            if m:
                return m.group(1)
        elif "youtu.be" in parsed.netloc:
            seg = parsed.path.strip("/").split("/")[0]
            if len(seg) == 11:
                return seg

        # TikTok: /video/ID or /photo/ID
        if "tiktok.com" in parsed.netloc:
            m = re.search(r"/(?:video|photo)/(\d+)", parsed.path)
            if m:
                return m.group(1)

        # Twitter / X: /status/ID
        if "twitter.com" in parsed.netloc or "x.com" in parsed.netloc:
            m = re.search(r"/status/(\d+)", parsed.path)
            if m:
                return m.group(1)

        # Reddit: /comments/ID/
        if "reddit.com" in parsed.netloc:
            m = re.search(r"/comments/([a-z0-9]+)/", parsed.path)
            if m:
                return m.group(1)
    except Exception:
        pass

    return None


def clean_comparable_name(name: str) -> str:
    """Normalize file stem or title for comparison."""
    # Strip extension
    stem = Path(name).stem.lower()
    # Replace non-alphanumeric with spaces (including underscores and hyphens)
    stem = re.sub(r"[^a-zA-Z0-9\s]", " ", stem)
    # Collapse whitespace
    return re.sub(r"\s+", " ", stem).strip()


def find_existing_duplicate(
    url: str,
    output_dir: Path,
    db_path: Optional[Path] = None,
    title: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Search SQLite history and target output directory for duplicate downloads.
    Returns match dictionary if an existing file is found on disk, None otherwise.
    """
    database_file = db_path or get_db_path(output_dir)

    # 1. Check history database
    if database_file.exists():
        try:
            conn = init_db(database_file)
            with conn:
                cursor = conn.execute(
                    """
                    SELECT title, primary_filepath, all_filepaths, filesize
                    FROM downloads
                    WHERE url = ? AND status = 'completed'
                    ORDER BY id DESC LIMIT 5
                    """,
                    (url,),
                )
                rows = cursor.fetchall()
            conn.close()

            for row in rows:
                # Check primary file
                primary = row["primary_filepath"]
                if primary:
                    p = Path(primary)
                    if p.is_file():
                        return {
                            "source": "history",
                            "path": p.resolve(),
                            "title": row["title"],
                            "filesize": p.stat().st_size,
                        }

                # Check all files
                all_raw = row["all_filepaths"]
                if all_raw:
                    try:
                        all_list = json.loads(all_raw)
                        for item in all_list:
                            p = Path(item)
                            if p.is_file():
                                return {
                                    "source": "history",
                                    "path": p.resolve(),
                                    "title": row["title"],
                                    "filesize": p.stat().st_size,
                                }
                    except Exception:
                        pass
        except Exception as exc:
            LOGGER.warning("Duplicate search in history failed: %s", exc)

    # 2. Check local filesystem by extracted ID
    media_id = extract_media_id_from_url(url)
    if media_id and output_dir.exists():
        try:
            # Search output directory and 1 level of subdirectories
            for candidate in output_dir.glob(f"*{media_id}*"):
                if candidate.is_file():
                    return {
                        "source": "filesystem_id",
                        "path": candidate.resolve(),
                        "title": candidate.stem,
                        "filesize": candidate.stat().st_size,
                    }
        except Exception:
            pass

    # 3. Check local filesystem by title comparison if title is supplied
    if title and output_dir.exists():
        clean_target = clean_comparable_name(title)
        if len(clean_target) >= 6:
            try:
                for candidate in output_dir.glob("*"):
                    if candidate.is_file() and clean_comparable_name(candidate.stem) == clean_target:
                        return {
                            "source": "filesystem_title",
                            "path": candidate.resolve(),
                            "title": candidate.stem,
                            "filesize": candidate.stat().st_size,
                        }
            except Exception:
                pass

    return None
