"""Persistent SQLite download history storage and query engine."""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger("universal_downloader")


def get_db_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "downloads.db"


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                uploader TEXT,
                uploader_id TEXT,
                platform TEXT,
                content_type TEXT,
                duration INTEGER,
                filesize INTEGER,
                format_id TEXT,
                primary_filepath TEXT,
                all_filepaths TEXT,
                thumbnail_url TEXT,
                status TEXT NOT NULL,
                error TEXT,
                downloaded_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_url ON downloads(url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_downloaded_at ON downloads(downloaded_at)")
    return conn


def record_download(
    db_path: Path,
    url: str,
    files: list[Path],
    metadata: dict[str, Any],
    status: str = "completed",
    error: Optional[str] = None,
) -> None:
    try:
        conn = init_db(db_path)
        with conn:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            primary_file = str(files[0]) if files else ""
            all_files_json = json.dumps([str(p) for p in files])

            conn.execute(
                """
                INSERT INTO downloads (
                    url, title, uploader, uploader_id, platform, content_type,
                    duration, filesize, format_id, primary_filepath, all_filepaths,
                    thumbnail_url, status, error, downloaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    metadata.get("title") or "unknown",
                    metadata.get("uploader") or "unknown",
                    metadata.get("uploader_id") or "unknown",
                    metadata.get("extractor") or metadata.get("platform") or "unknown",
                    metadata.get("content_type") or "video",
                    int(metadata.get("duration") or 0),
                    int(metadata.get("filesize") or metadata.get("filesize_approx") or 0),
                    str(metadata.get("format_id") or ""),
                    primary_file,
                    all_files_json,
                    metadata.get("thumbnail") or "",
                    status,
                    error,
                    now_iso,
                ),
            )
        conn.close()
    except Exception as exc:
        LOGGER.warning("Could not record download to history database: %s", exc)


def get_history(
    db_path: Path,
    limit: int = 50,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    try:
        conn = init_db(db_path)
        with conn:
            if search:
                pattern = f"%{search.strip()}%"
                cursor = conn.execute(
                    """
                    SELECT * FROM downloads
                    WHERE title LIKE ? OR uploader LIKE ? OR url LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM downloads ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()

        results = [dict(row) for row in rows]
        conn.close()
        return results
    except Exception as exc:
        LOGGER.warning("Could not retrieve download history: %s", exc)
        return []


def clear_history(db_path: Path) -> int:
    if not db_path.exists():
        return 0

    try:
        conn = init_db(db_path)
        with conn:
            cursor = conn.execute("DELETE FROM downloads")
            count = cursor.rowcount
        conn.close()
        return count
    except Exception as exc:
        LOGGER.warning("Could not clear download history: %s", exc)
        return 0
