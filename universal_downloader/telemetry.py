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
            from ctypes import Structure, byref, c_byte, c_ulong

            class SYSTEM_POWER_STATUS(Structure):
                _fields_ = [
                    ("ACLineStatus", c_byte),
                    ("BatteryFlag", c_byte),
                    ("BatteryLifePercent", c_byte),
                    ("SystemStatusFlag", c_byte),
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


def build_heartbeat_payload(data_dir: Optional[Path] = None) -> dict[str, Any]:
    """Construct the anonymous telemetry payload."""
    return {
        "install_id": get_or_create_install_id(data_dir),
        "device_type": detect_device_type(),
        "os_name": detect_os_name(),
        "device_model": detect_device_model() or "Unknown Model",
        "app_version": __version__,
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

        sql_query = (
            f"SELECT record_device_heartbeat("
            f"'{esc_id}'::UUID, "
            f"'{esc_type}', "
            f"'{esc_os}', "
            f"'{esc_model}', "
            f"'{esc_ver}'"
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

    payload = build_heartbeat_payload(data_dir)

    def _worker() -> None:
        push_heartbeat_to_neon(url, token, payload, timeout=timeout)

    if async_send:
        t = threading.Thread(target=_worker, name="UD-Telemetry", daemon=True)
        t.start()
        return True
    else:
        return push_heartbeat_to_neon(url, token, payload, timeout=timeout)


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
            # Column indices or dictionary
            tot_dev = st.get("total_unique_devices", 0) if isinstance(st, dict) else st[0]
            desktops = st.get("desktop_pcs", 0) if isinstance(st, dict) else st[1]
            laptops = st.get("laptops", 0) if isinstance(st, dict) else st[2]
            androids = st.get("android_devices", 0) if isinstance(st, dict) else st[3]
            act_30 = st.get("active_last_30_days", 0) if isinstance(st, dict) else st[5]
            act_7 = st.get("active_last_7_days", 0) if isinstance(st, dict) else st[6]

            lines.append(f"Total Unique Installations: {tot_dev:,}")
            if tot_dev > 0:
                lines.append(f"Active (Past 30 Days):      {act_30:,} ({(act_30/tot_dev)*100:5.1f}%)")
                lines.append(f"Active (Past 7 Days):       {act_7:,} ({(act_7/tot_dev)*100:5.1f}%)")
                lines.append("")
                lines.append("Form Factor Breakdown:")
                lines.append(f"  • Desktop PC:             {desktops:,} ({(desktops/tot_dev)*100:5.1f}%)")
                lines.append(f"  • Laptop:                 {laptops:,} ({(laptops/tot_dev)*100:5.1f}%)")
                lines.append(f"  • Android:                {androids:,} ({(androids/tot_dev)*100:5.1f}%)")
        else:
            lines.append("Connected to Neon: No device heartbeats recorded yet.")
    else:
        lines.append("Neon database endpoint not configured or offline.")
        lines.append("To connect, set NEON_DATABASE_URL and NEON_TELEMETRY_KEY in .env.")
        lines.append("See docs/TELEMETRY_SETUP.md for the 1-minute setup instructions.")

    lines.append("=" * 80)
    return "\n".join(lines)
