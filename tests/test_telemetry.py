"""Unit tests for anonymous device telemetry, install ID persistence, and maintainer analytics."""

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.models import AppConfig
from universal_downloader.telemetry import (
    _sql_escape,
    build_heartbeat_payload,
    detect_device_type,
    detect_os_name,
    fetch_github_release_stats,
    format_analytics_dashboard,
    get_or_create_install_id,
    is_telemetry_enabled,
    push_heartbeat_to_neon,
    send_telemetry_heartbeat,
)


def test_sql_escape():
    assert _sql_escape("normal") == "normal"
    assert _sql_escape("O'Reilly") == "O''Reilly"
    assert _sql_escape(None) == ""
    assert _sql_escape(123) == "123"


def test_get_or_create_install_id_generates_and_persists(tmp_path: Path):
    id_1 = get_or_create_install_id(tmp_path)
    # Must be valid UUID
    parsed = uuid.UUID(id_1)
    assert parsed.version == 4

    # Second call returns the exact same ID
    id_2 = get_or_create_install_id(tmp_path)
    assert id_1 == id_2

    # Check file exists
    id_file = tmp_path / "device_id.json"
    assert id_file.is_file()
    data = json.loads(id_file.read_text(encoding="utf-8"))
    assert data["install_id"] == id_1


def test_get_or_create_install_id_recovers_from_corrupted_file(tmp_path: Path):
    id_file = tmp_path / "device_id.json"
    id_file.write_text("invalid json garbage", encoding="utf-8")

    fresh_id = get_or_create_install_id(tmp_path)
    assert uuid.UUID(fresh_id).version == 4


def test_is_telemetry_enabled_opt_out(monkeypatch):
    assert is_telemetry_enabled() is True

    monkeypatch.setenv("UD_NO_TELEMETRY", "1")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("UD_NO_TELEMETRY")
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("DO_NOT_TRACK")
    cfg = AppConfig(no_telemetry=True)
    assert is_telemetry_enabled(cfg) is False


def test_build_heartbeat_payload_structure(tmp_path: Path):
    payload = build_heartbeat_payload(tmp_path)
    assert "install_id" in payload
    assert uuid.UUID(payload["install_id"]).version == 4
    assert "device_type" in payload
    assert payload["device_type"] in ("Desktop PC", "Laptop", "Android", "macOS", "Linux Desktop", "Unknown")
    assert "os_name" in payload
    assert "device_model" in payload
    assert "app_version" in payload


def test_detect_device_type_android(monkeypatch):
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    assert detect_device_type() == "Android"


def test_detect_device_type_windows_mocked():
    if sys.platform != "win32":
        pytest.skip("Windows-only ctypes power status test")

    import ctypes

    class FakePowerStatus:
        def __init__(self, flag, pct):
            self.BatteryFlag = flag
            self.BatteryLifePercent = pct

    # Flag 128 = No battery (Desktop PC)
    with patch("ctypes.windll.kernel32.GetSystemPowerStatus") as mock_power:
        def side_effect(byref_sps):
            sps = FakePowerStatus(128, 255)
            # copy attributes to the passed ctypes structure
            byref_sps._obj.BatteryFlag = sps.BatteryFlag
            byref_sps._obj.BatteryLifePercent = sps.BatteryLifePercent
            return 1

        mock_power.side_effect = side_effect
        assert detect_device_type() == "Desktop PC"

    # Flag 1 = High Battery (Laptop)
    with patch("ctypes.windll.kernel32.GetSystemPowerStatus") as mock_power:
        def side_effect(byref_sps):
            byref_sps._obj.BatteryFlag = 1
            byref_sps._obj.BatteryLifePercent = 95
            return 1

        mock_power.side_effect = side_effect
        assert detect_device_type() == "Laptop"


def test_fetch_github_release_stats_calculation():
    sample_api_response = [
        {
            "tag_name": "v3.0.0",
            "name": "Release 3.0.0",
            "published_at": "2026-11-18T10:00:00Z",
            "assets": [
                {"name": "universal_downloader_windows.exe", "download_count": 500},
                {"name": "universal_downloader.msi", "download_count": 250},
                {"name": "universal_downloader.apk", "download_count": 300},
                {"name": "source.tar.gz", "download_count": 50},
            ],
        },
        {
            "tag_name": "v2.0.0",
            "name": "Release 2.0.0",
            "published_at": "2026-11-10T10:00:00Z",
            "assets": [
                {"name": "installer.exe", "download_count": 100},
                {"name": "app.apk", "download_count": 100},
            ],
        },
    ]

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_api_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        stats = fetch_github_release_stats(repo="test/repo")
        assert stats["success"] is True
        assert stats["total_downloads"] == 1300
        assert stats["windows_downloads"] == 850  # 500 + 250 + 100
        assert stats["android_downloads"] == 400  # 300 + 100
        assert stats["other_downloads"] == 50
        assert len(stats["releases"]) == 2


def test_push_heartbeat_to_neon():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        payload = {
            "install_id": str(uuid.uuid4()),
            "device_type": "Desktop PC",
            "os_name": "Windows 11",
            "device_model": "Custom PC",
            "app_version": "3.4.0",
        }
        res = push_heartbeat_to_neon("https://neon.mock/sql", "test_key", payload)
        assert res is True
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test_key"
        body = json.loads(req.data.decode("utf-8"))
        assert "record_device_heartbeat" in body["query"]
        assert "Desktop PC" in body["query"]


def test_send_telemetry_heartbeat_disabled_skips(monkeypatch):
    monkeypatch.setenv("UD_NO_TELEMETRY", "1")
    with patch("universal_downloader.telemetry.push_heartbeat_to_neon") as mock_push:
        res = send_telemetry_heartbeat(async_send=False)
        assert res is False
        mock_push.assert_not_called()


def test_format_analytics_dashboard_rendering():
    gh_stats = {
        "success": True,
        "repo": "Antony-Gh/Universal-Donwloader",
        "total_downloads": 1000,
        "windows_downloads": 600,
        "android_downloads": 300,
        "other_downloads": 100,
        "releases": [
            {"tag": "v3.0.0", "downloads": 700},
            {"tag": "v2.0.0", "downloads": 300},
        ],
    }

    neon_stats = {
        "stats": {
            "rows": [
                {
                    "total_unique_devices": 500,
                    "desktop_pcs": 250,
                    "laptops": 150,
                    "android_devices": 100,
                    "other_devices": 0,
                    "active_last_30_days": 400,
                    "active_last_7_days": 250,
                }
            ]
        }
    }

    report = format_analytics_dashboard(gh_stats, neon_stats)
    assert "Global Telemetry & Distribution Dashboard" in report
    assert "1,000" in report
    assert "Windows (.exe / .msi):  600 ( 60.0%)" in report
    assert "Android (.apk):         300 ( 30.0%)" in report
    assert "Total Unique Installations: 500" in report
    assert "Desktop PC:             250 ( 50.0%)" in report
    assert "Laptop:                 150 ( 30.0%)" in report
    assert "Android:                100 ( 20.0%)" in report
