"""Unit tests for smart scheduling, wall-clock timing, and power condition gates."""

from datetime import datetime
from unittest.mock import patch

import pytest
from universal_downloader.smart_scheduler import (
    check_smart_download_conditions,
    get_power_status,
    parse_schedule_time,
    seconds_until_schedule,
)


def test_parse_schedule_time_valid():
    """Verify valid 24-hour HH:MM strings parse accurately."""
    assert parse_schedule_time("00:00") == (0, 0)
    assert parse_schedule_time("02:30") == (2, 30)
    assert parse_schedule_time("14:45") == (14, 45)
    assert parse_schedule_time("23:59") == (23, 59)


def test_parse_schedule_time_invalid():
    """Verify invalid time strings raise ValueError."""
    with pytest.raises(ValueError):
        parse_schedule_time("")
    with pytest.raises(ValueError):
        parse_schedule_time("25:00")
    with pytest.raises(ValueError):
        parse_schedule_time("12:60")
    with pytest.raises(ValueError):
        parse_schedule_time("invalid")
    with pytest.raises(ValueError):
        parse_schedule_time("12:00:00")


def test_seconds_until_schedule_future_today():
    """Verify seconds calculation for a target later today."""
    now = datetime(2026, 11, 19, 10, 0, 0)
    # Target is 12:30 (2 hours and 30 minutes = 9000 seconds)
    secs = seconds_until_schedule("12:30", now=now)
    assert secs == 9000


def test_seconds_until_schedule_wraps_to_tomorrow():
    """Verify seconds calculation for a target earlier than current time rolls over to tomorrow."""
    now = datetime(2026, 11, 19, 23, 0, 0)
    # Target is 02:00 tomorrow (3 hours = 10800 seconds)
    secs = seconds_until_schedule("02:00", now=now)
    assert secs == 10800


def test_check_smart_download_conditions_battery_low():
    """Verify smart gate pauses when battery is low (< 20% and discharging)."""
    mock_power = {"on_ac": False, "battery_percent": 14, "is_battery_low": True}
    with patch("universal_downloader.smart_scheduler.get_power_status", return_value=mock_power):
        can_proceed, reason = check_smart_download_conditions(pause_on_battery=True)
        assert can_proceed is False
        assert "14%" in reason
        assert "paused" in reason.lower()

    # Disabled flag allows proceed
    with patch("universal_downloader.smart_scheduler.get_power_status", return_value=mock_power):
        can_proceed, _ = check_smart_download_conditions(pause_on_battery=False)
        assert can_proceed is True


def test_check_smart_download_conditions_ac_connected():
    """Verify smart gate allows proceed when plugged into AC power."""
    mock_power = {"on_ac": True, "battery_percent": 15, "is_battery_low": False}
    with patch("universal_downloader.smart_scheduler.get_power_status", return_value=mock_power):
        can_proceed, _ = check_smart_download_conditions(pause_on_battery=True)
        assert can_proceed is True
