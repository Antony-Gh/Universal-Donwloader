"""Tests for logging filters, secret redactions, and error recovery classification."""

import logging

from universal_downloader.logging_utils import (
    SecretFilter,
    clean_error_message,
    format_download_error,
    is_non_retryable_error,
    is_tiktok_rehydration_error,
)
from universal_downloader.models import Platform


def test_secret_filter():
    filt = SecretFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Connecting with api_key=secret123 and password=pass456",
        args=(),
        exc_info=None,
    )
    filt.filter(record)
    assert "secret123" not in record.msg
    assert "pass456" not in record.msg
    assert "[REDACTED]" in record.msg


def test_clean_error_message():
    raw = "\x1b[31mERROR: [youtube] Video unavailable\x1b[0m"
    cleaned = clean_error_message(raw)
    assert cleaned == "[youtube] Video unavailable"


def test_error_retryability_classification():
    # Permanent errors must NOT be retried
    assert is_non_retryable_error("HTTP Error 404: Not Found") is True
    assert is_non_retryable_error("Video is private") is True
    assert is_non_retryable_error("Sign in to confirm your age") is True
    assert is_non_retryable_error("Unsupported URL") is True

    # Transient errors (HTTP 429, rate limits) MUST be retryable
    assert is_non_retryable_error("HTTP Error 429: Too Many Requests") is False
    assert is_non_retryable_error("Rate limit reached. Try again later.") is False
    assert is_non_retryable_error("Connection timed out") is False
    assert is_non_retryable_error("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed") is False


def test_ytdlp_logger_warning_filter(monkeypatch):
    from universal_downloader.extractor import YTDLPLogger
    from universal_downloader.models import AppConfig

    logger = YTDLPLogger(AppConfig())
    logged_warnings = []
    logged_debugs = []

    monkeypatch.setattr("universal_downloader.extractor.LOGGER.warning", lambda msg: logged_warnings.append(msg))
    monkeypatch.setattr("universal_downloader.extractor.LOGGER.debug", lambda msg: logged_debugs.append(msg))

    # Noise warnings should be downgraded to debug (case-insensitive)
    logger.warning("Some web client https formats have been skipped as they are missing a url. The current session may have the SSAP (server-side ads) experiment")
    logger.warning("[youtube] PmZdQ4MiqwQ: Some ios client https formats have been skipped as they are missing a URL. YouTube may have enabled the SABR-only streaming experiment for the current session.")
    logger.warning("[youtube:tab] YouTube said: INFO - 1 unavailable video is hidden")
    assert len(logged_warnings) == 0
    assert len(logged_debugs) == 3

    # Real warnings should be kept as warning
    logger.warning("Actual problem occurred during format selection")
    assert len(logged_warnings) == 1


def test_tiktok_rehydration_predicate():
    msg = "ERROR: Unable to extract universal data"
    assert is_tiktok_rehydration_error(msg) is True
    assert is_tiktok_rehydration_error("Other error") is False


def test_format_download_error_suggestions():
    # TikTok suggestions
    tt_err = Exception("Unable to extract universal data")
    formatted = format_download_error(tt_err, Platform.TIKTOK)
    assert "browser cookies" in formatted

    # DPAPI / App-Bound Encryption suggestions
    dpapi_err = Exception("DPAPI decryption failed for Chromium cookie database")
    formatted_dpapi = format_download_error(dpapi_err)
    assert "App-Bound Encryption" in formatted_dpapi
    assert "cookies.txt" in formatted_dpapi
