"""Tests for the SQLite download history database."""

import tempfile
from pathlib import Path

from universal_downloader.history import clear_history, get_db_path, get_history, record_download


def test_history_crud():
    with tempfile.TemporaryDirectory() as td:
        db_path = get_db_path(Path(td))

        # Initial history should be empty
        assert get_history(db_path) == []

        # Record a download
        record_download(
            db_path=db_path,
            url="https://youtube.com/watch?v=item1",
            files=[Path(td) / "item1.mp4"],
            metadata={"title": "Introduction to Python", "uploader": "CodeAcademy", "duration": 120, "filesize": 1048576},
            status="completed",
        )

        record_download(
            db_path=db_path,
            url="https://youtube.com/watch?v=item2",
            files=[Path(td) / "item2.mp4"],
            metadata={"title": "Advanced C# Development", "uploader": "DevGuru", "duration": 360, "filesize": 5242880},
            status="completed",
        )

        # Retrieve all
        items = get_history(db_path)
        assert len(items) == 2
        assert items[0]["title"] == "Advanced C# Development"
        assert items[1]["title"] == "Introduction to Python"

        # Search
        csharp_items = get_history(db_path, search="C#")
        assert len(csharp_items) == 1
        assert csharp_items[0]["uploader"] == "DevGuru"

        # Search by uploader
        code_items = get_history(db_path, search="CodeAcademy")
        assert len(code_items) == 1

        # Clear
        deleted = clear_history(db_path)
        assert deleted == 2
        assert get_history(db_path) == []
