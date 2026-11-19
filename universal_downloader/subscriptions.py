"""Channel and playlist subscription manager backed by SQLite."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Optional

from universal_downloader.models import AppConfig

LOGGER = logging.getLogger("universal_downloader")


def _ensure_subscriptions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            label TEXT,
            audio_only INTEGER NOT NULL DEFAULT 0,
            quality TEXT NOT NULL DEFAULT 'best',
            max_downloads INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL,
            last_synced_at TEXT
        )
        """
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "url": row["url"],
        "label": row["label"] or "",
        "audio_only": bool(row["audio_only"]),
        "quality": row["quality"],
        "max_downloads": int(row["max_downloads"]),
        "created_at": row["created_at"],
        "last_synced_at": row["last_synced_at"],
    }


def add_subscription(
    db_path: Path,
    url: str,
    *,
    label: Optional[str] = None,
    audio_only: bool = False,
    quality: str = "best",
    max_downloads: int = 5,
) -> dict[str, Any]:
    """Add or update a channel/playlist subscription in the SQLite database."""
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("Subscription URL must not be empty.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    bounded_max = max(1, min(int(max_downloads or 5), 500))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_subscriptions_table(conn)
        conn.execute(
            """
            INSERT INTO subscriptions (url, label, audio_only, quality, max_downloads, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                label = COALESCE(excluded.label, subscriptions.label),
                audio_only = excluded.audio_only,
                quality = excluded.quality,
                max_downloads = excluded.max_downloads
            """,
            (clean_url, label, 1 if audio_only else 0, quality or "best", bounded_max, now_iso),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM subscriptions WHERE url = ?", (clean_url,)).fetchone()
        return _row_to_dict(row)


def remove_subscription(db_path: Path, url_or_id: str) -> bool:
    """Remove a subscription by its numeric ID or exact URL. Returns True if deleted."""
    target = (url_or_id or "").strip()
    if not target or not db_path.exists():
        return False

    with sqlite3.connect(db_path) as conn:
        _ensure_subscriptions_table(conn)
        if target.isdigit():
            cur = conn.execute("DELETE FROM subscriptions WHERE id = ? OR url = ?", (int(target), target))
        else:
            cur = conn.execute("DELETE FROM subscriptions WHERE url = ?", (target,))
        conn.commit()
        return cur.rowcount > 0


def list_subscriptions(db_path: Path) -> list[dict[str, Any]]:
    """Return all configured subscriptions ordered by ID."""
    if not db_path.exists():
        return []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_subscriptions_table(conn)
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id ASC").fetchall()
        return [_row_to_dict(r) for r in rows]


def sync_subscriptions(
    base_config: AppConfig,
    db_path: Path,
    *,
    engine_factory: Optional[Callable[[AppConfig], Any]] = None,
) -> dict[str, Any]:
    """Sync all subscribed channels/playlists using a persistent download archive."""
    subs = list_subscriptions(db_path)
    if not subs:
        return {"total": 0, "synced": 0, "failed": 0, "items": []}

    if engine_factory is None:
        from universal_downloader.engine import DownloadEngine

        engine_factory = DownloadEngine

    archive_file = base_config.download_archive or (db_path.parent / "subscriptions_archive.txt")
    synced_count = 0
    failed_count = 0
    item_reports: list[dict[str, Any]] = []

    for sub in subs:
        sub_cfg = replace(
            base_config,
            audio_only=bool(sub["audio_only"]),
            quality=str(sub["quality"] or base_config.quality),
            max_downloads=int(sub["max_downloads"] or base_config.max_downloads or 5),
            download_archive=archive_file,
        )
        engine = engine_factory(sub_cfg)
        try:
            res = engine.download(sub["url"])
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(db_path) as conn:
                _ensure_subscriptions_table(conn)
                conn.execute(
                    "UPDATE subscriptions SET last_synced_at = ? WHERE id = ?",
                    (now_iso, sub["id"]),
                )
                conn.commit()
            synced_count += 1
            item_reports.append(
                {
                    "id": sub["id"],
                    "url": sub["url"],
                    "success": True,
                    "files": [str(p) for p in res.files],
                }
            )
        except Exception as exc:
            LOGGER.warning("Subscription sync failed for %s: %s", sub["url"], exc)
            failed_count += 1
            item_reports.append(
                {
                    "id": sub["id"],
                    "url": sub["url"],
                    "success": False,
                    "error": str(exc),
                }
            )

    return {
        "total": len(subs),
        "synced": synced_count,
        "failed": failed_count,
        "archive": str(archive_file),
        "items": item_reports,
    }
