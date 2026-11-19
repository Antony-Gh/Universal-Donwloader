from unittest.mock import MagicMock
from pathlib import Path
import pytest

from scripts.check_extractor_health import (
    HealthCheckResult,
    generate_markdown_report,
    run_health_check,
)


def test_generate_markdown_report():
    results = [
        HealthCheckResult(
            platform="YouTube",
            url="https://youtube.com/watch?v=123",
            success=True,
            latency_sec=1.2,
            title="Sample Video",
            stream_count=5,
        ),
        HealthCheckResult(
            platform="TikTok",
            url="https://tiktok.com/@u/video/456",
            success=False,
            latency_sec=2.5,
            error_message="HTTP 403 Forbidden",
        ),
    ]

    report = generate_markdown_report(results)
    assert "Extractor Health Status" in report
    assert "YouTube" in report
    assert "Operational" in report
    assert "TikTok" in report
    assert "HTTP 403 Forbidden" in report


def test_run_health_check_success():
    mock_engine = MagicMock()
    mock_engine.inspect.return_value = {
        "title": "Test Title",
        "formats": [{"format_id": "18"}, {"format_id": "22"}],
    }

    res = run_health_check(mock_engine, "TestPlatform", "https://example.com/video")
    assert res.success is True
    assert res.platform == "TestPlatform"
    assert res.title == "Test Title"
    assert res.stream_count == 2
    assert res.latency_sec >= 0


def test_run_health_check_failure():
    mock_engine = MagicMock()
    mock_engine.inspect.side_effect = RuntimeError("Extraction failed")

    res = run_health_check(mock_engine, "FailingPlatform", "https://example.com/fail")
    assert res.success is False
    assert res.platform == "FailingPlatform"
    assert "Extraction failed" in res.error_message
