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
