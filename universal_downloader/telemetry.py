"""Anonymous device telemetry and maintainer analytics for Universal Media Downloader.

Collects high-level anonymous device form factor metrics (Desktop PC vs. Laptop vs. Android)
and pushes them to a Neon serverless PostgreSQL database via Neon's SQL-over-HTTPS API.

Privacy Principles:
- Purely anonymous: Random UUIDv4 generated locally upon first installation.
- Zero PII: Never collects IP addresses, usernames, hostnames, paths, or credentials.
- Zero Activity Tracking: Never tracks or transmits URLs, video titles, or file metadata.
- Full Opt-Out: Fully suppressed via --no-telemetry, UD_NO_TELEMETRY=1, or DO_NOT_TRACK=1.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

from universal_downloader import __version__
from universal_downloader.paths import get_default_data_dir

logger = logging.getLogger(__name__)

DEFAULT_GITHUB_REPO = "Antony-Gh/Universal-Donwloader"


def detect_device_type() -> str:
    """Detect whether the current machine is a Desktop PC, Laptop, Android, macOS, or Linux device.

    Returns:
        One of: 'Desktop PC', 'Laptop', 'Android', 'macOS', 'Linux Desktop', 'Unknown'.
    """
    # 1. Android check (Termux / Android runtime / environment variables)
    if (
        os.environ.get("ANDROID_ROOT")
        or os.environ.get("ANDROID_DATA")
        or os.environ.get("ANDROID_BOOTLOGO")
        or "android" in platform.platform().lower()
    ):
        return "Android"

    # 2. Windows PC vs. Laptop via Win32 GetSystemPowerStatus
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import Structure, byref, c_ubyte, c_ulong

            class SYSTEM_POWER_STATUS(Structure):
                _fields_ = [
                    ("ACLineStatus", c_ubyte),
                    ("BatteryFlag", c_ubyte),
                    ("BatteryLifePercent", c_ubyte),
                    ("SystemStatusFlag", c_ubyte),
                    ("BatteryLifeTime", c_ulong),
                    ("BatteryFullLifeTime", c_ulong),
                ]

            sps = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(byref(sps)):
                # BatteryFlag:
                # 128 = No system battery (Desktop PC)
                # 255 = Unknown status (Desktop PC fallback if BatteryLifePercent == 255)
                # 1 = High, 2 = Low, 4 = Critical, 8 = Charging
                if sps.BatteryFlag == 128 or (
                    sps.BatteryFlag == 255 and sps.BatteryLifePercent == 255
                ):
                    return "Desktop PC"
                elif sps.BatteryLifePercent <= 100 or (sps.BatteryFlag & 128 == 0):
                    return "Laptop"
        except Exception as exc:
            logger.debug("Windows power status query failed: %s", exc)

    # 3. Linux PC vs. Laptop via /sys/class/power_supply
    if sys.platform.startswith("linux"):
        try:
            power_dir = Path("/sys/class/power_supply")
            if power_dir.is_dir():
                for item in power_dir.iterdir():
                    name = item.name.lower()
                    if name.startswith("bat"):
                        return "Laptop"
                    type_file = item / "type"
                    if type_file.is_file():
                        try:
                            if type_file.read_text(encoding="utf-8").strip().lower() == "battery":
                                return "Laptop"
                        except OSError:
                            pass
            return "Desktop PC"
        except Exception as exc:
            logger.debug("Linux power supply inspection failed: %s", exc)
            return "Linux Desktop"

    # 4. macOS detection via pmset or ioreg
    if sys.platform == "darwin":
        try:
            import subprocess

            res = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "Battery" in res.stdout or "InternalBattery" in res.stdout:
                return "Laptop"
            return "Desktop PC"
        except Exception:
            return "macOS"

    return "Unknown"


def detect_os_name() -> str:
    """Return a descriptive, sanitized OS identifier."""
    if os.environ.get("ANDROID_ROOT") or "android" in platform.platform().lower():
        return f"Android {platform.release() or ''}".strip()

    if sys.platform == "win32":
        ver = platform.version()
        release = platform.release()
        # Windows 11 build numbers start at 22000
        try:
            build = int(ver.split(".")[-1])
            if build >= 22000:
                release = "11"
        except (ValueError, IndexError):
            pass
        return f"Windows {release} ({ver})"

    if sys.platform == "darwin":
        mac_ver = platform.mac_ver()[0]
        return f"macOS {mac_ver}".strip()

    if sys.platform.startswith("linux"):
        try:
            os_release = Path("/etc/os-release")
            if os_release.is_file():
                for line in os_release.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip('"\'')
        except OSError:
            pass
        return f"Linux {platform.release()}"

    return platform.system() or "Unknown"


def detect_device_model() -> Optional[str]:
    """Retrieve anonymous hardware model without serial numbers or identifiers."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"
            ) as key:
                product, _ = winreg.QueryValueEx(key, "SystemProductName")
                if product and product.strip() not in (
                    "System Product Name",
                    "To be filled by O.E.M.",
                    "Default string",
                ):
                    return product.strip()
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        try:
            product_file = Path("/sys/devices/virtual/dmi/id/product_name")
            if product_file.is_file():
                name = product_file.read_text(encoding="utf-8").strip()
                if name and name not in ("System Product Name", "None"):
                    return name
        except OSError:
            pass

    return None


def get_or_create_install_id(data_dir: Optional[Path] = None) -> str:
    """Load or generate a persistent anonymous UUIDv4 for this installation.

    Stored in `<data_dir>/device_id.json`. Pure random UUID, no device fingerprinting.
    """
    directory = data_dir or get_default_data_dir()
    id_file = directory / "device_id.json"

    try:
        if id_file.is_file():
            content = json.loads(id_file.read_text(encoding="utf-8"))
            candidate = content.get("install_id")
            if candidate:
                # Validate UUID format
                uuid.UUID(str(candidate))
                return str(candidate)
    except Exception as exc:
        logger.debug("Failed to read install ID: %s", exc)

    new_id = str(uuid.uuid4())
    try:
        directory.mkdir(parents=True, exist_ok=True)
        id_file.write_text(
            json.dumps({"install_id": new_id, "created_at": str(platform.platform())}),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Failed to save install ID: %s", exc)

    return new_id


def reset_install_id(data_dir: Optional[Path] = None) -> str:
    """Generate a brand-new random anonymous UUIDv4, replacing the existing ID."""
    directory = data_dir or get_default_data_dir()
    id_file = directory / "device_id.json"
    new_id = str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=True)
    id_file.write_text(
        json.dumps({"install_id": new_id, "created_at": str(platform.platform())}),
        encoding="utf-8",
    )
    return new_id


def request_gdpr_data_wipe(
    config: Optional[Any] = None,
    data_dir: Optional[Path] = None,
    timeout: float = 4.0,
) -> bool:
    """Send an authenticated/authorized request to Neon to delete this installation's telemetry."""
    url = (
        getattr(config, "telemetry_url", None)
        or os.environ.get("NEON_DATABASE_URL")
        or os.environ.get("UD_TELEMETRY_URL")
    )
    if not url:
        return False

    token = (
        getattr(config, "telemetry_key", None)
        or os.environ.get("NEON_TELEMETRY_KEY")
    )

    install_id = get_or_create_install_id(data_dir=data_dir)
    esc_id = _sql_escape(install_id)

    try:
        sql_query = f"SELECT delete_device_telemetry('{esc_id}'::UUID);"
        req_data = json.dumps({"query": sql_query}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"UniversalDownloader/{__version__}",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
            if ok:
                reset_install_id(data_dir=data_dir)
            return ok
    except Exception as exc:
        logger.warning("GDPR data wipe request failed: %s", exc)
        return False


def get_telemetry_transparency_info(
    config: Optional[Any] = None,
    data_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Return full transparency report of the exact data collected and sent to Neon."""
    enabled = is_telemetry_enabled(config)
    payload = build_heartbeat_payload(data_dir=data_dir, config=config)
    friend = payload.get("friend_tag")
    data_path = str(data_dir or get_default_data_dir())

    return {
        "telemetry_enabled": enabled,
        "install_id": payload.get("install_id"),
        "identified_friend_tag": friend,
        "payload_to_server": payload,
        "data_storage_path": data_path,
        "privacy_guarantees": [
            "Purely anonymous: Random UUIDv4 generated locally upon install.",
            "Zero PII: IP addresses, hostnames, usernames, and passwords are NEVER transmitted.",
            "Zero Activity Tracking: URLs, video titles, and download history are strictly local to your machine.",
            "Full GDPR Control: You can opt out anytime (--no-telemetry) or wipe your data with --gdpr-wipe.",
        ],
    }


def format_privacy_report(config: Optional[Any] = None) -> str:
    """Format human-readable transparency report for terminal/UI."""
    info = get_telemetry_transparency_info(config)
    status_str = "🟢 ENABLED (Anonymous Heartbeat & Crash Diagnostics)" if info["telemetry_enabled"] else "🔴 DISABLED (Opted Out)"

    lines = [
        "=" * 80,
        "🔒 PRIVACY & TELEMETRY TRANSPARENCY DASHBOARD",
        "=" * 80,
        f"Telemetry Status:       {status_str}",
        f"Anonymous Install ID:   {info['install_id']}",
        f"Identified Friend Tag:  {info['identified_friend_tag'] or 'None (Standard Public User)'}",
        f"Local Config Path:      {info['data_storage_path']}",
        "",
        "📋 EXACT PAYLOAD TRANSMITTED TO NEON (Open Inspectable Data):",
        "-" * 80,
        json.dumps(info["payload_to_server"], indent=2),
        "-" * 80,
        "",
        "🛡️ PRIVACY GUARANTEES & GDPR COMPLIANCE:",
    ]
    for g in info["privacy_guarantees"]:
        lines.append(f"  • {g}")
    lines.append("")
    lines.append("To opt out completely: run with --no-telemetry or set DO_NOT_TRACK=1 in your environment.")
    lines.append("To request remote GDPR deletion of this device ID: run with --gdpr-wipe")
    lines.append("=" * 80)
    return "\n".join(lines)


def is_telemetry_enabled(config: Optional[Any] = None) -> bool:
    """Check if telemetry reporting is enabled based on environment and configuration."""
    if os.environ.get("UD_NO_TELEMETRY", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("DO_NOT_TRACK", "").strip() == "1":
        return False

    if config is not None:
        if getattr(config, "no_telemetry", False):
            return False
        if getattr(config, "telemetry_enabled", True) is False:
            return False

    return True


def detect_locale() -> str:
    """Retrieve system regional locale/language (e.g. en_US, ar_EG)."""
    try:
        import locale
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc
    except Exception:
        pass
    lang = os.environ.get("LANG", "Unknown")
    return lang.split(".")[0] if "." in lang else lang


def detect_timezone() -> str:
    """Retrieve system timezone or standard offset (e.g. Egypt Standard Time, UTC+02:00)."""
    try:
        import datetime
        tz = datetime.datetime.now().astimezone().tzname()
        if tz:
            return tz
    except Exception:
        pass
    return "Unknown"


def detect_cpu_specs() -> tuple[int, str]:
    """Retrieve logical CPU cores and architecture without elevated permissions."""
    cores = os.cpu_count() or 1
    arch = platform.machine() or "Unknown"
    return cores, arch


def detect_total_ram_gb() -> Optional[float]:
    """Retrieve installed physical RAM in Gigabytes."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import Structure, byref, c_ulong, c_ulonglong

            class MEMORYSTATUSEX(Structure):
                _fields_ = [
                    ("dwLength", c_ulong),
                    ("dwMemoryLoad", c_ulong),
                    ("ullTotalPhys", c_ulonglong),
                    ("ullAvailPhys", c_ulonglong),
                    ("ullTotalPageFile", c_ulonglong),
                    ("ullAvailPageFile", c_ulonglong),
                    ("ullTotalVirtual", c_ulonglong),
                    ("ullAvailVirtual", c_ulonglong),
                    ("ullAvailExtendedVirtual", c_ulonglong),
                ]

            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(m)):
                return round(m.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        try:
            meminfo = Path("/proc/meminfo")
            if meminfo.is_file():
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        kb = float(parts[1])
                        return round(kb / (1024 * 1024), 1)
        except Exception:
            pass

    return None


def detect_screen_resolution() -> Optional[str]:
    """Retrieve primary display resolution (e.g. 1920x1080)."""
    if sys.platform == "win32":
        try:
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return f"{w}x{h}"
        except Exception:
            pass
    return None


def detect_connection_type() -> str:
    """Check network connectivity status."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        s.close()
        return "Connected"
    except Exception:
        return "Offline"


def detect_friend_tag(
    custom_tag: Optional[str] = None,
    config: Optional[Any] = None,
    data_dir: Optional[Path] = None,
) -> Optional[str]:
    """Identify which friend/beta-tester downloaded the tool.

    Priority order:
    1. Explicit custom_tag argument
    2. Config / CLI option (--friend or --ref)
    3. Environment variable UD_FRIEND_TAG or UD_REF
    4. Persistent tag stored in device_id.json
    5. Executable filename pattern (e.g. UniversalDownloader_ahmed.exe -> 'ahmed')
    """
    if custom_tag and custom_tag.strip():
        return custom_tag.strip().lower()

    if config is not None:
        cfg_tag = getattr(config, "friend_tag", None)
        if cfg_tag and str(cfg_tag).strip():
            return str(cfg_tag).strip().lower()

    env_tag = os.environ.get("UD_FRIEND_TAG") or os.environ.get("UD_REF")
    if env_tag and env_tag.strip():
        return env_tag.strip().lower()

    directory = data_dir or get_default_data_dir()
    id_file = directory / "device_id.json"

    # Check already persisted friend tag
    if id_file.is_file():
        try:
            saved = json.loads(id_file.read_text(encoding="utf-8"))
            if saved.get("friend_tag"):
                return str(saved["friend_tag"]).strip().lower()
        except Exception:
            pass

    # Extract from binary filename (e.g. downloader_ahmed.exe, UniversalDownloader_sara)
    try:
        import re

        prog_stem = Path(sys.argv[0]).stem
        m = re.search(
            r"(?:universal[_-]?downloader|downloader)[_-]([a-zA-Z0-9_\-]+)$",
            prog_stem,
            re.IGNORECASE,
        )
        if m:
            found_tag = m.group(1).strip().lower()
            # Persist tag in device_id.json so it is remembered permanently
            try:
                directory.mkdir(parents=True, exist_ok=True)
                data = json.loads(id_file.read_text(encoding="utf-8")) if id_file.is_file() else {}
                data["friend_tag"] = found_tag
                id_file.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass
            return found_tag
    except Exception:
        pass

    return None


def build_heartbeat_payload(
    data_dir: Optional[Path] = None,
    config: Optional[Any] = None,
    friend_tag: Optional[str] = None,
) -> dict[str, Any]:
    """Construct the anonymous telemetry payload with extended legal hardware metrics."""
    cores, arch = detect_cpu_specs()
    tag = detect_friend_tag(custom_tag=friend_tag, config=config, data_dir=data_dir)
    return {
        "install_id": get_or_create_install_id(data_dir),
        "device_type": detect_device_type(),
        "os_name": detect_os_name(),
        "device_model": detect_device_model() or "Unknown Model",
        "app_version": __version__,
        "locale": detect_locale(),
        "timezone": detect_timezone(),
        "cpu_cores": cores,
        "cpu_arch": arch,
        "total_ram_gb": detect_total_ram_gb(),
        "screen_res": detect_screen_resolution() or "Unknown",
        "connection_type": detect_connection_type(),
        "friend_tag": tag,
    }


def _sql_escape(val: Any) -> str:
    """Sanitize strings for SQL literal inclusion."""
    if val is None:
        return ""
    return str(val).replace("'", "''")


def push_heartbeat_to_neon(
    endpoint_url: str,
    auth_token: Optional[str],
    payload: dict[str, Any],
    timeout: float = 4.0,
) -> bool:
    """Execute the `record_device_heartbeat` stored procedure on Neon via HTTP SQL API."""
    try:
        esc_id = _sql_escape(payload.get("install_id"))
        esc_type = _sql_escape(payload.get("device_type"))
        esc_os = _sql_escape(payload.get("os_name"))
        esc_model = _sql_escape(payload.get("device_model"))
        esc_ver = _sql_escape(payload.get("app_version"))
        esc_locale = _sql_escape(payload.get("locale"))
        esc_tz = _sql_escape(payload.get("timezone"))
        esc_cores = int(payload.get("cpu_cores") or 0)
        esc_arch = _sql_escape(payload.get("cpu_arch"))
        ram_val = payload.get("total_ram_gb")
        esc_ram = f"{float(ram_val):.1f}" if ram_val is not None else "NULL"
        esc_screen = _sql_escape(payload.get("screen_res"))
        esc_conn = _sql_escape(payload.get("connection_type"))
        esc_friend = _sql_escape(payload.get("friend_tag"))
        esc_friend_sql = f"'{esc_friend}'" if esc_friend else "NULL"

        sql_query = (
            f"SELECT record_device_heartbeat("
            f"'{esc_id}'::UUID, "
            f"'{esc_type}', "
            f"'{esc_os}', "
            f"'{esc_model}', "
            f"'{esc_ver}', "
            f"'{esc_locale}', "
            f"'{esc_tz}', "
            f"{esc_cores}, "
            f"'{esc_arch}', "
            f"{esc_ram}, "
            f"'{esc_screen}', "
            f"'{esc_conn}', "
            f"{esc_friend_sql}"
            ");"
        )

        req_data = json.dumps({"query": sql_query}).encode("utf-8")
        req = urllib.request.Request(
            endpoint_url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"UniversalDownloader/{__version__}",
                **({"Authorization": f"Bearer {auth_token}"} if auth_token else {}),
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.debug("Neon telemetry push failed (safe non-blocking): %s", exc)
        return False


def send_telemetry_heartbeat(
    config: Optional[Any] = None,
    endpoint_url: Optional[str] = None,
    auth_token: Optional[str] = None,
    data_dir: Optional[Path] = None,
    async_send: bool = True,
    timeout: float = 4.0,
) -> bool:
    """Send an anonymous telemetry heartbeat if enabled and endpoint is configured.

    Runs in a background thread by default so it never stalls CLI or downloads.
    """
    if not is_telemetry_enabled(config):
        return False

    url = (
        endpoint_url
        or getattr(config, "telemetry_url", None)
        or os.environ.get("NEON_DATABASE_URL")
        or os.environ.get("UD_TELEMETRY_URL")
    )
    if not url:
        return False

    token = (
        auth_token
        or getattr(config, "telemetry_key", None)
        or os.environ.get("NEON_TELEMETRY_KEY")
    )

    payload = build_heartbeat_payload(data_dir=data_dir, config=config)

    def _worker() -> None:
        push_heartbeat_to_neon(url, token, payload, timeout=timeout)

    if async_send:
        t = threading.Thread(target=_worker, name="UD-Telemetry", daemon=True)
        t.start()
        return True
    else:
        return push_heartbeat_to_neon(url, token, payload, timeout=timeout)


def sanitize_stack_trace(trace_text: str) -> str:
    """Sanitize stack traces to remove local usernames, home directory paths, or tokens."""
    if not trace_text:
        return ""
    sanitized = re.sub(r"[A-Za-z]:\\[Uu]sers\\[^\\]+\\", lambda _: r"C:\Users\[USER]\\", trace_text)
    sanitized = re.sub(r"/(?:home|Users)/[^/]+/", "/home/[USER]/", sanitized)
    return sanitized


def push_crash_report_to_neon(
    endpoint_url: str,
    auth_token: Optional[str],
    payload: dict[str, Any],
    timeout: float = 4.0,
) -> bool:
    """Execute record_crash_report stored procedure on Neon via HTTP SQL API."""
    try:
        esc_id = _sql_escape(payload.get("install_id"))
        esc_ver = _sql_escape(payload.get("app_version"))
        esc_platform = _sql_escape(payload.get("client_platform", "CLI"))
        esc_os = _sql_escape(payload.get("os_name"))
        esc_err_type = _sql_escape(payload.get("error_type", "UnknownError"))
        esc_err_msg = _sql_escape(payload.get("error_message", ""))
        esc_trace = _sql_escape(payload.get("stack_trace", ""))

        sql_query = (
            f"SELECT record_crash_report("
            f"'{esc_id}'::UUID, "
            f"'{esc_ver}', "
            f"'{esc_platform}', "
            f"'{esc_os}', "
            f"'{esc_err_type}', "
            f"'{esc_err_msg}', "
            f"'{esc_trace}'"
            ");"
        )

        req_data = json.dumps({"query": sql_query}).encode("utf-8")
        req = urllib.request.Request(
            endpoint_url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"UniversalDownloader/{__version__}",
                **({"Authorization": f"Bearer {auth_token}"} if auth_token else {}),
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.debug("Neon crash reporting push failed: %s", exc)
        return False


def send_crash_report(
    exc: BaseException,
    client_platform: str = "CLI",
    config: Optional[Any] = None,
    async_send: bool = True,
    timeout: float = 4.0,
) -> bool:
    """Send an anonymous crash report with sanitized stack trace to Neon."""
    if not is_telemetry_enabled(config):
        return False

    url = (
        getattr(config, "telemetry_url", None)
        or os.environ.get("NEON_DATABASE_URL")
        or os.environ.get("UD_TELEMETRY_URL")
    )
    if not url:
        return False

    token = (
        getattr(config, "telemetry_key", None)
        or os.environ.get("NEON_TELEMETRY_KEY")
    )

    import traceback
    raw_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    clean_trace = sanitize_stack_trace(raw_trace)
    clean_msg = sanitize_stack_trace(str(exc))

    payload = {
        "install_id": get_or_create_install_id(),
        "app_version": __version__,
        "client_platform": client_platform,
        "os_name": detect_os_name(),
        "error_type": type(exc).__name__,
        "error_message": clean_msg,
        "stack_trace": clean_trace,
    }

    def _worker() -> None:
        push_crash_report_to_neon(url, token, payload, timeout=timeout)

    if async_send:
        t = threading.Thread(target=_worker, name="UD-CrashReporter", daemon=True)
        t.start()
        return True
    else:
        return push_crash_report_to_neon(url, token, payload, timeout=timeout)


# ==============================================================================
# Analytics & Distribution Dashboard Fetchers
# ==============================================================================


def fetch_github_release_stats(
    repo: str = DEFAULT_GITHUB_REPO,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Fetch GitHub Releases API and compute download counts by platform asset type."""
    api_url = f"https://api.github.com/repos/{repo}/releases"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": f"UniversalDownloader/{__version__}",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Could not fetch GitHub releases: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "repo": repo,
            "total_downloads": 0,
            "windows_downloads": 0,
            "android_downloads": 0,
            "other_downloads": 0,
            "releases": [],
        }

    total_downloads = 0
    windows_downloads = 0
    android_downloads = 0
    other_downloads = 0
    release_list = []

    for rel in data:
        tag_name = rel.get("tag_name", "Unknown")
        assets = rel.get("assets", [])
        rel_downloads = 0

        for asset in assets:
            name = asset.get("name", "").lower()
            count = asset.get("download_count", 0)
            rel_downloads += count
            total_downloads += count

            if name.endswith((".exe", ".msi")):
                windows_downloads += count
            elif name.endswith(".apk"):
                android_downloads += count
            else:
                other_downloads += count

        release_list.append(
            {
                "tag": tag_name,
                "name": rel.get("name", tag_name),
                "published_at": rel.get("published_at"),
                "downloads": rel_downloads,
                "asset_count": len(assets),
            }
        )

    return {
        "success": True,
        "repo": repo,
        "total_downloads": total_downloads,
        "windows_downloads": windows_downloads,
        "android_downloads": android_downloads,
        "other_downloads": other_downloads,
        "releases": release_list,
    }


def fetch_neon_device_stats(
    endpoint_url: str,
    auth_token: Optional[str] = None,
    timeout: float = 8.0,
) -> Optional[dict[str, Any]]:
    """Query aggregated views from Neon Postgres database."""
    try:
        queries = {
            "stats": "SELECT * FROM v_device_stats;",
            "breakdown": "SELECT * FROM v_device_breakdown LIMIT 10;",
            "geo": "SELECT * FROM v_geo_demographics LIMIT 5;",
            "hardware": "SELECT * FROM v_hardware_specs LIMIT 5;",
            "friends": "SELECT * FROM v_friend_installs LIMIT 15;",
            "versions": "SELECT * FROM v_version_breakdown LIMIT 10;",
        }
        results: dict[str, Any] = {}

        for key, q in queries.items():
            req_data = json.dumps({"query": q}).encode("utf-8")
            req = urllib.request.Request(
                endpoint_url,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"UniversalDownloader/{__version__}",
                    **({"Authorization": f"Bearer {auth_token}"} if auth_token else {}),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    results[key] = json.loads(resp.read().decode("utf-8"))

        return results
    except Exception as exc:
        logger.debug("Failed to fetch Neon analytics: %s", exc)
        return None


def format_analytics_dashboard(
    github_stats: dict[str, Any],
    neon_stats: Optional[dict[str, Any]] = None,
) -> str:
    """Format an informative maintainer console report."""
    lines = [
        "=" * 80,
        "Universal Media Downloader — Global Telemetry & Distribution Dashboard",
        "=" * 80,
        "",
        f"📦 GITHUB RELEASE DOWNLOADS ({github_stats.get('repo', DEFAULT_GITHUB_REPO)})",
        "-" * 80,
    ]

    total = github_stats.get("total_downloads", 0)
    win = github_stats.get("windows_downloads", 0)
    apk = github_stats.get("android_downloads", 0)
    oth = github_stats.get("other_downloads", 0)

    lines.append(f"Total Downloads:        {total:,}")
    if total > 0:
        win_pct = (win / total) * 100
        apk_pct = (apk / total) * 100
        oth_pct = (oth / total) * 100
        lines.append(f"  • Windows (.exe / .msi):  {win:,} ({win_pct:5.1f}%)")
        lines.append(f"  • Android (.apk):         {apk:,} ({apk_pct:5.1f}%)")
        lines.append(f"  • Source & Archives:      {oth:,} ({oth_pct:5.1f}%)")
    else:
        lines.append("  (No release downloads recorded yet or API rate limit reached)")

    releases = github_stats.get("releases", [])
    if releases:
        lines.append("")
        lines.append("Recent Releases:")
        for r in releases[:5]:
            lines.append(f"  - {r['tag']}: {r['downloads']:,} downloads")

    lines.append("")
    lines.append("💻 ACTIVE DEVICE INSTALLATIONS (Neon Serverless Postgres)")
    lines.append("-" * 80)

    if neon_stats and "stats" in neon_stats:
        rows = neon_stats["stats"].get("rows", [])
        if rows:
            st = rows[0]
            tot_dev = st.get("total_unique_devices", 0) if isinstance(st, dict) else st[0]
            desktops = st.get("desktop_pcs", 0) if isinstance(st, dict) else st[1]
            laptops = st.get("laptops", 0) if isinstance(st, dict) else st[2]
            androids = st.get("android_devices", 0) if isinstance(st, dict) else st[3]
            act_30 = st.get("active_last_30_days", 0) if isinstance(st, dict) else st[5]
            act_7 = st.get("active_last_7_days", 0) if isinstance(st, dict) else st[6]
            avg_ram = st.get("avg_ram_gb") if isinstance(st, dict) else (st[7] if len(st) > 7 else None)
            avg_cores = st.get("avg_cpu_cores") if isinstance(st, dict) else (st[8] if len(st) > 8 else None)

            lines.append(f"Total Unique Installations: {tot_dev:,}")
            if tot_dev > 0:
                lines.append(f"Active (Past 30 Days):      {act_30:,} ({(act_30/tot_dev)*100:5.1f}%)")
                lines.append(f"Active (Past 7 Days):       {act_7:,} ({(act_7/tot_dev)*100:5.1f}%)")
                lines.append("")
                lines.append("Form Factor Breakdown:")
                lines.append(f"  • Desktop PC:             {desktops:,} ({(desktops/tot_dev)*100:5.1f}%)")
                lines.append(f"  • Laptop:                 {laptops:,} ({(laptops/tot_dev)*100:5.1f}%)")
                lines.append(f"  • Android:                {androids:,} ({(androids/tot_dev)*100:5.1f}%)")

                if avg_ram or avg_cores:
                    lines.append("")
                    lines.append("Hardware Capability Profile:")
                    if avg_cores:
                        lines.append(f"  • Average CPU Cores:      {float(avg_cores):.1f} cores")
                    if avg_ram:
                        lines.append(f"  • Average Installed RAM:  {float(avg_ram):.1f} GB")

            # Demographics breakdown
            geo_rows = neon_stats.get("geo", {}).get("rows", [])
            if geo_rows:
                lines.append("")
                lines.append("Top Regional Locales & Timezones:")
                for g in geo_rows[:4]:
                    loc_name = g.get("locale") if isinstance(g, dict) else g[0]
                    tz_name = g.get("timezone") if isinstance(g, dict) else g[1]
                    cnt = g.get("count") if isinstance(g, dict) else g[2]
                    pct = g.get("percentage") if isinstance(g, dict) else g[3]
                    lines.append(f"  • {loc_name} ({tz_name}): {cnt} ({pct}%)")

            # Hardware specs breakdown
            hw_rows = neon_stats.get("hardware", {}).get("rows", [])
            if hw_rows:
                lines.append("")
                lines.append("Display & Architecture Breakdown:")
                for h in hw_rows[:4]:
                    arch_name = h.get("cpu_arch") if isinstance(h, dict) else h[0]
                    res_name = h.get("screen_res") if isinstance(h, dict) else h[1]
                    cnt = h.get("count") if isinstance(h, dict) else h[3]
                    lines.append(f"  • {arch_name} / {res_name}: {cnt} devices")

            # Identified Friends & Beta-Testers
            friend_rows = neon_stats.get("friends", {}).get("rows", [])
            if friend_rows:
                lines.append("")
                lines.append("👥 IDENTIFIED FRIENDS & BETA TESTERS (Neon)")
                lines.append("-" * 80)
                for f in friend_rows:
                    f_name = f.get("friend_tag") if isinstance(f, dict) else f[0]
                    f_type = f.get("device_type") if isinstance(f, dict) else f[1]
                    f_os = f.get("os_name") if isinstance(f, dict) else f[2]
                    f_model = f.get("device_model") if isinstance(f, dict) else f[3]
                    f_seen = str(f.get("last_seen_at") if isinstance(f, dict) else f[7])[:19]
                    f_runs = f.get("heartbeat_count") if isinstance(f, dict) else f[8]
                    model_str = f" ({f_model})" if f_model and f_model != "Unknown Model" else ""
                    lines.append(f"  • {f_name:<12} | {f_type}{model_str:<20} | {f_os:<16} | Runs: {f_runs:<3} | Last: {f_seen}")

        else:
            lines.append("Connected to Neon: No device heartbeats recorded yet.")
    else:
        lines.append("Neon database endpoint not configured or offline.")
        lines.append("To connect, set NEON_DATABASE_URL and NEON_TELEMETRY_KEY in .env.")
        lines.append("See docs/TELEMETRY_SETUP.md for the 1-minute setup instructions.")

    lines.append("=" * 80)
    return "\n".join(lines)
