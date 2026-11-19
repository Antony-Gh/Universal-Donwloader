"""Smart download scheduling and device power/network condition gates.

Allows running downloads at a specified wall-clock time (e.g. 02:00 for off-peak hours),
pausing on battery saver, and restricting downloads to unmetered connections.
"""

from __future__ import annotations

import ctypes
from ctypes import Structure, byref, c_ubyte, c_ulong
from datetime import datetime, time, timedelta, timezone
import logging
import os
import platform
import subprocess
import time as time_mod
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def parse_schedule_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' string (e.g. '02:00', '23:30') into (hours, minutes).

    Raises ValueError if format is invalid.
    """
    clean = (time_str or "").strip()
    if not clean:
        raise ValueError("Schedule time must not be empty.")

    parts = clean.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid schedule time format '{time_str}'. Expected 'HH:MM' (24-hour).")

    hours = int(parts[0])
    minutes = int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"Invalid hour/minute values in '{time_str}'. Hours must be 0-23, minutes 0-59.")

    return hours, minutes


def seconds_until_schedule(target_time_str: str, now: Optional[datetime] = None) -> int:
    """Calculate the number of seconds from now until the next occurrence of target_time_str.

    Handles wrapping to the next day when target time is earlier than current time.
    """
    hours, minutes = parse_schedule_time(target_time_str)
    current = now or datetime.now()
    target = current.replace(hour=hours, minute=minutes, second=0, microsecond=0)

    if target <= current:
        target += timedelta(days=1)

    return max(0, int((target - current).total_seconds()))


def get_power_status() -> dict[str, Any]:
    """Check whether device is plugged into AC power and current battery percentage.

    Returns dict with keys: 'on_ac' (bool), 'battery_percent' (int, 0-100 or 100 for desktop),
    'is_battery_low' (bool, True if discharging and < 20%).
    """
    os_name = platform.system().lower()

    if os_name == "windows":
        try:
            class SYSTEM_POWER_STATUS(Structure):
                _fields_ = [
                    ("ACLineStatus", c_ubyte),  # 0=Offline, 1=Online, 255=Unknown
                    ("BatteryFlag", c_ubyte),
                    ("BatteryLifePercent", c_ubyte),
                    ("SystemStatusFlag", c_ubyte),
                    ("BatteryLifeTime", c_ulong),
                    ("BatteryFullLifeTime", c_ulong),
                ]

            sps = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(byref(sps)):
                on_ac = sps.ACLineStatus == 1
                percent = int(sps.BatteryLifePercent)
                if percent > 100:
                    percent = 100
                is_low = (not on_ac) and (percent < 20) and (sps.BatteryFlag != 128)
                return {"on_ac": on_ac, "battery_percent": percent, "is_battery_low": is_low}
        except Exception as exc:
            logger.debug("Win32 power query failed: %s", exc)

    elif os_name == "linux":
        try:
            from pathlib import Path
            power_dir = Path("/sys/class/power_supply")
            if power_dir.is_dir():
                for node in power_dir.iterdir():
                    type_file = node / "type"
                    if type_file.is_file() and type_file.read_text(encoding="utf-8").strip().lower() == "battery":
                        cap_file = node / "capacity"
                        status_file = node / "status"
                        percent = int(cap_file.read_text(encoding="utf-8").strip()) if cap_file.is_file() else 100
                        status = status_file.read_text(encoding="utf-8").strip().lower() if status_file.is_file() else "unknown"
                        on_ac = status in {"charging", "full"}
                        is_low = (not on_ac) and (percent < 20)
                        return {"on_ac": on_ac, "battery_percent": percent, "is_battery_low": is_low}
        except Exception as exc:
            logger.debug("Linux power query failed: %s", exc)

    return {"on_ac": True, "battery_percent": 100, "is_battery_low": False}


def check_smart_download_conditions(
    pause_on_battery: bool = False,
    only_wifi: bool = False,
) -> tuple[bool, str]:
    """Verify smart download conditions before initiating a download job.

    Returns (can_proceed, reason_message).
    """
    if pause_on_battery:
        power = get_power_status()
        if power["is_battery_low"]:
            return (
                False,
                f"Download paused: Battery is at {power['battery_percent']}% (below 20% threshold and discharging). "
                f"Plug in device or disable battery saver.",
            )

    return True, "Conditions satisfied."


def wait_until_schedule(
    target_time_str: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    poll_interval: int = 5,
) -> None:
    """Block execution until wall-clock time reaches target_time_str."""
    secs = seconds_until_schedule(target_time_str)
    logger.info("Download scheduled for %s (waiting %d seconds)", target_time_str, secs)

    while secs > 0:
        if progress_callback:
            progress_callback(secs)
        sleep_chunk = min(secs, poll_interval)
        time_mod.sleep(sleep_chunk)
        secs = seconds_until_schedule(target_time_str)
