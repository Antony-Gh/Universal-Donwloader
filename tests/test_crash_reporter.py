from unittest.mock import MagicMock, patch
import pytest

from universal_downloader.telemetry import (
    sanitize_stack_trace,
    push_crash_report_to_neon,
    send_crash_report,
)


def test_sanitize_stack_trace():
    raw = (
        'File "C:\\Users\\anthonygaius\\Projects\\Universal_Downloader\\test.py", line 12\n'
        'File "/home/anthonygaius/src/main.py", line 45'
    )
    cleaned = sanitize_stack_trace(raw)
    assert "anthonygaius" not in cleaned
    assert "[USER]" in cleaned


@patch("urllib.request.urlopen")
def test_push_crash_report_to_neon(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    payload = {
        "install_id": "00000000-0000-0000-0000-000000000000",
        "app_version": "3.9.0",
        "client_platform": "CLI",
        "os_name": "Windows 11",
        "error_type": "ValueError",
        "error_message": "Invalid argument",
        "stack_trace": "Traceback ...",
    }

    ok = push_crash_report_to_neon("https://neon.tech/sql", "test-token", payload)
    assert ok is True
    assert mock_urlopen.called


@patch("universal_downloader.telemetry.push_crash_report_to_neon", return_value=True)
def test_send_crash_report_with_env(mock_push, monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "https://neon.tech/sql")
    monkeypatch.setenv("NEON_TELEMETRY_KEY", "token-123")

    try:
        raise RuntimeError("Something went wrong during download")
    except RuntimeError as ex:
        sent = send_crash_report(ex, client_platform="CLI", async_send=False)
        assert sent is True
        assert mock_push.called
        call_payload = mock_push.call_args[0][2]
        assert call_payload["error_type"] == "RuntimeError"
        assert "Something went wrong" in call_payload["error_message"]
