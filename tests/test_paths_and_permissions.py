"""Tests for path resolution, write permission verification, and read-only directory fallbacks."""

import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from universal_downloader.config import build_config
from universal_downloader.history import get_db_path
from universal_downloader.logging_utils import configure_logging
from universal_downloader.models import AppConfig, DetectedTarget, Platform
from universal_downloader.paths import (
    get_default_data_dir,
    get_default_download_dir,
    get_default_log_dir,
    is_directory_writable,
    is_system_or_program_dir,
)
from universal_downloader.engine import DownloadEngine


def test_default_paths_structure():
    log_dir = get_default_log_dir()
    data_dir = get_default_data_dir()
    download_dir = get_default_download_dir()

    assert isinstance(log_dir, Path)
    assert isinstance(data_dir, Path)
    assert isinstance(download_dir, Path)

    # Must contain product name or system path
    assert "universal" in str(log_dir).lower()
    assert "universal" in str(data_dir).lower()


def test_is_directory_writable():
    with tempfile.TemporaryDirectory() as td:
        assert is_directory_writable(Path(td)) is True

    # Non-existent drive or impossible path
    assert is_directory_writable(Path("Z:\\non_existent_folder_xyz_123456789")) is False


def test_is_system_or_program_dir():
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", "C:\\Program Files")
        assert is_system_or_program_dir(Path(pf)) is True
        assert is_system_or_program_dir(Path(pf) / "Universal Media Downloader") is True
        windir = os.environ.get("SystemRoot", "C:\\Windows")
        assert is_system_or_program_dir(Path(windir)) is True
    else:
        assert is_system_or_program_dir(Path("/usr/bin")) is True
        assert is_system_or_program_dir(Path("/opt/app")) is True


def test_configure_logging_resilient_to_permission_denied():
    # Simulate a read-only or restricted log directory that raises PermissionError
    unwritable_dir = Path("C:\\Program Files\\Universal Media Downloader\\Logs") if os.name == "nt" else Path("/root/logs")

    cfg = AppConfig(log_dir=unwritable_dir)

    # Must not raise PermissionError: [WinError 5] Access is denied
    configure_logging(cfg)

    # cfg.log_dir should have fallen back to a writable directory
    assert cfg.log_dir != unwritable_dir
    assert cfg.log_dir.exists()


def test_get_db_path_fallback_when_output_dir_unwritable():
    unwritable_output = Path("C:\\Program Files\\Universal Media Downloader\\downloads") if os.name == "nt" else Path("/root/downloads")

    db_path = get_db_path(unwritable_output)

    # Must not be inside the unwritable output dir
    assert not str(db_path).startswith(str(unwritable_output))
    assert db_path.name == "downloads.db"
    assert db_path.parent.exists()


def test_engine_output_template_fallback_when_unwritable():
    unwritable_output = Path("C:\\Program Files\\Universal Media Downloader\\downloads") if os.name == "nt" else Path("/root/downloads")
    cfg = AppConfig(output_dir=unwritable_output)
    engine = DownloadEngine(cfg)

    target = DetectedTarget(
        original_url="https://youtube.com/watch?v=123",
        normalized_url="https://youtube.com/watch?v=123",
        platform=Platform.YOUTUBE,
    )

    tmpl = engine.choose_output_template(target)
    # Output template must not be located in Program Files
    assert not tmpl.startswith(str(unwritable_output))
    assert "youtube" in tmpl.lower()
