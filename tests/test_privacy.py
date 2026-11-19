import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from universal_downloader.models import AppConfig
from universal_downloader.telemetry import (
    format_privacy_report,
    get_telemetry_transparency_info,
    reset_install_id,
    request_gdpr_data_wipe,
)


def test_get_telemetry_transparency_info(tmp_path: Path):
    config = AppConfig()
    info = get_telemetry_transparency_info(config, data_dir=tmp_path)

    assert info["telemetry_enabled"] is True
    assert "install_id" in info
    assert "payload_to_server" in info
    assert len(info["privacy_guarantees"]) >= 3
    assert "Zero PII" in " ".join(info["privacy_guarantees"])


def test_reset_install_id(tmp_path: Path):
    id1 = reset_install_id(data_dir=tmp_path)
    id2 = reset_install_id(data_dir=tmp_path)

    assert id1 != id2
    assert (tmp_path / "device_id.json").exists()


def test_format_privacy_report(tmp_path: Path):
    config = AppConfig()
    report = format_privacy_report(config)

    assert "PRIVACY & TELEMETRY TRANSPARENCY DASHBOARD" in report
    assert "Zero PII" in report
    assert "EXACT PAYLOAD TRANSMITTED" in report


@patch("urllib.request.urlopen")
def test_request_gdpr_data_wipe(mock_urlopen, tmp_path: Path):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    config = AppConfig(telemetry_url="https://neon.tech/sql", telemetry_key="dummy-key")
    ok = request_gdpr_data_wipe(config, data_dir=tmp_path)

    assert ok is True
    assert mock_urlopen.called
    req_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert "delete_device_telemetry" in req_body["query"]
