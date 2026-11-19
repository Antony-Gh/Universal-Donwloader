"""Tests for universal_downloader.subscriptions (channel/playlist watchlist & sync)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.cli import main
from universal_downloader.models import AppConfig, DownloadResult
from universal_downloader.subscriptions import (
    add_subscription,
    list_subscriptions,
    remove_subscription,
    sync_subscriptions,
)


def test_add_list_and_remove_subscriptions(tmp_path: Path) -> None:
    db = tmp_path / "history.db"

    sub1 = add_subscription(db, "https://www.youtube.com/@ChannelOne", label="Channel One", max_downloads=3)
    sub2 = add_subscription(db, "https://www.youtube.com/playlist?list=PL123", audio_only=True, quality="audio")

    assert sub1["id"] == 1
    assert sub1["max_downloads"] == 3
    assert sub2["audio_only"] is True

    # Upsert updates existing URL instead of duplicating
    updated1 = add_subscription(db, "https://www.youtube.com/@ChannelOne", max_downloads=8)
    assert updated1["id"] == 1
    assert updated1["max_downloads"] == 8

    all_subs = list_subscriptions(db)
    assert len(all_subs) == 2

    # Remove by numeric ID
    assert remove_subscription(db, "1") is True
    assert len(list_subscriptions(db)) == 1

    # Remove by URL
    assert remove_subscription(db, "https://www.youtube.com/playlist?list=PL123") is True
    assert list_subscriptions(db) == []


def test_sync_subscriptions_updates_last_synced_at_and_uses_archive(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    add_subscription(db, "https://www.youtube.com/@Creator", max_downloads=4)

    fake_file = tmp_path / "ep1.mp4"
    fake_file.write_bytes(b"mp4")
    captured_configs: list[AppConfig] = []

    def _factory(cfg: AppConfig):
        captured_configs.append(cfg)
        m = MagicMock()
        m.download.return_value = DownloadResult(
            success=True,
            url="https://www.youtube.com/@Creator",
            files=[fake_file],
        )
        return m

    summary = sync_subscriptions(AppConfig(output_dir=tmp_path), db, engine_factory=_factory)
    assert summary["total"] == 1
    assert summary["synced"] == 1
    assert summary["failed"] == 0
    assert len(captured_configs) == 1
    assert captured_configs[0].max_downloads == 4
    assert captured_configs[0].download_archive is not None

    subs_after = list_subscriptions(db)
    assert subs_after[0]["last_synced_at"] is not None


def test_cli_subscribe_list_and_unsubscribe_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    feed = "https://www.youtube.com/@TechFeed"

    with patch("sys.argv", ["downloader.py", "--output", str(tmp_path), "--subscribe", feed, "--json"]):
        assert main() == 0
    sub_out = json.loads(capsys.readouterr().out)
    assert sub_out["success"] is True
    assert sub_out["subscription"]["url"] == feed

    with patch("sys.argv", ["downloader.py", "--output", str(tmp_path), "--list-subscriptions", "--json"]):
        assert main() == 0
    list_out = json.loads(capsys.readouterr().out)
    assert list_out["count"] == 1

    with patch("sys.argv", ["downloader.py", "--output", str(tmp_path), "--unsubscribe", "1", "--json"]):
        assert main() == 0
    unsub_out = json.loads(capsys.readouterr().out)
    assert unsub_out["success"] is True
