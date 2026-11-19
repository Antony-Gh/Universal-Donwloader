"""Remote version lifecycle and deprecation enforcement for Universal Media Downloader.

Allows maintainers to deprecate or retire older application versions (e.g. disabling versions < v3.6.0)
remotely via Neon serverless PostgreSQL or GitHub raw version_policy.json fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from universal_downloader import __version__

logger = logging.getLogger(__name__)

DEFAULT_RAW_POLICY_URL = (
    "https://raw.githubusercontent.com/Antony-Gh/Universal-Donwloader/master/version_policy.json"
)
DEFAULT_LATEST_RELEASE_URL = (
    "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest"
)

DEFAULT_FALLBACK_POLICY: dict[str, Any] = {
    "min_supported_version": "3.6.0",
    "latest_version": "3.6.0",
    "blocked_versions": [],
    "sunset_message": (
        "This version of Universal Media Downloader has reached End of Life and is no longer supported.\n"
        "Please download the latest release to continue downloading media."
    ),
    "download_url": DEFAULT_LATEST_RELEASE_URL,
    "enforcement_mode": "block",  # 'block', 'warn', 'allow'
}


def parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse a semantic version string into a comparable integer tuple.

    Examples:
        '3.6.0' -> (3, 6, 0)
        'v3.4.1-beta' -> (3, 4, 1)
        '4.0' -> (4, 0, 0)
    """
    clean = str(version_str).strip().lstrip("vV")
    # Strip any prerelease or build tags (e.g. -beta, +build123)
    clean = re.split(r"[-+]", clean)[0]

    parts: list[int] = []
    for chunk in clean.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts[:3])


def fetch_remote_version_policy(
    neon_url: Optional[str] = None,
    auth_token: Optional[str] = None,
    raw_github_url: str = DEFAULT_RAW_POLICY_URL,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Retrieve version policy from Neon database or GitHub raw fallback.

    Returns DEFAULT_FALLBACK_POLICY on complete network timeout/failure.
    """
    url = (
        neon_url
        or os.environ.get("NEON_DATABASE_URL")
        or os.environ.get("UD_TELEMETRY_URL")
    )
    token = (
        auth_token
        or os.environ.get("NEON_TELEMETRY_KEY")
    )

    # 1. Try Neon Serverless Postgres SQL endpoint
    if url:
        try:
            req_data = json.dumps({"query": "SELECT get_version_policy();"}).encode("utf-8")
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
                if 200 <= resp.status < 300:
                    data = json.loads(resp.read().decode("utf-8"))
                    rows = data.get("rows", [])
                    if rows:
                        row = rows[0]
                        res = row.get("get_version_policy") if isinstance(row, dict) else row[0]
                        if isinstance(res, dict):
                            return {**DEFAULT_FALLBACK_POLICY, **res}
                        elif isinstance(res, str):
                            return {**DEFAULT_FALLBACK_POLICY, **json.loads(res)}
        except Exception as exc:
            logger.debug("Neon version policy query failed, falling back to GitHub: %s", exc)

    # 2. Try Raw GitHub version_policy.json
    try:
        req = urllib.request.Request(
            raw_github_url,
            headers={
                "User-Agent": f"UniversalDownloader/{__version__}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                raw_json = json.loads(resp.read().decode("utf-8"))
                return {**DEFAULT_FALLBACK_POLICY, **raw_json}
    except Exception as exc:
        logger.debug("GitHub raw version policy fetch failed, falling back to local defaults: %s", exc)

    # 3. Safe embedded fallback
    return dict(DEFAULT_FALLBACK_POLICY)


def evaluate_version_support(
    current_version: str,
    policy: Optional[dict[str, Any]] = None,
) -> tuple[bool, str, str]:
    """Check whether current_version satisfies the remote lifecycle policy.

    Returns:
        (is_allowed, status_code, explanation_message)
        status_code is one of: 'allowed', 'deprecated', 'blocked', 'update_available'.
    """
    active_policy = policy or DEFAULT_FALLBACK_POLICY
    min_ver_str = active_policy.get("min_supported_version", "3.6.0")
    latest_ver_str = active_policy.get("latest_version", "3.6.0")
    blocked_list = [str(v).strip().lstrip("vV") for v in active_policy.get("blocked_versions", [])]

    clean_curr = str(current_version).strip().lstrip("vV")
    curr_tup = parse_version_tuple(clean_curr)
    min_tup = parse_version_tuple(min_ver_str)
    latest_tup = parse_version_tuple(latest_ver_str)

    # 1. Check explicitly blacklisted versions
    if clean_curr in blocked_list:
        msg = f"Version v{current_version} has been explicitly revoked or blocked due to security or critical platform errors."
        return False, "blocked", msg

    # 2. Check if below minimum supported version
    if curr_tup < min_tup:
        msg = (
            f"Universal Media Downloader v{current_version} has reached End of Life.\n"
            f"Minimum supported version is v{min_ver_str} (Latest: v{latest_ver_str}).\n"
            f"{active_policy.get('sunset_message', '')}"
        )
        return False, "deprecated", msg

    # 3. Check if newer version is available
    if curr_tup < latest_tup:
        msg = f"Universal Media Downloader v{latest_ver_str} is available (current: v{current_version})."
        return True, "update_available", msg

    return True, "allowed", f"Version v{current_version} is supported and up to date."


def render_sunset_banner(
    current_version: str,
    policy: dict[str, Any],
) -> str:
    """Render a prominent ASCII End-of-Life warning / block banner."""
    min_ver = policy.get("min_supported_version", "3.6.0")
    latest_ver = policy.get("latest_version", "3.6.0")
    download_url = policy.get("download_url", DEFAULT_LATEST_RELEASE_URL)
    sunset_msg = policy.get("sunset_message", "").strip()

    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════╗",
        "║                     VERSION DEPRECATION / END OF LIFE                        ║",
        "╚══════════════════════════════════════════════════════════════════════════════╝",
        "",
        f"Your installed version (v{current_version}) has reached End of Life.",
        f"Minimum required version: v{min_ver}  (Latest release: v{latest_ver})",
        "",
        sunset_msg,
        "",
        "Please update to continue downloading media with the latest site extractors:",
        f"👉 Download: {download_url}",
        "═" * 80,
    ]
    return "\n".join(lines)


def enforce_version_policy(
    current_version: str = __version__,
    config: Optional[Any] = None,
    allow_force: bool = False,
) -> tuple[bool, str]:
    """Execute the deprecation gate. Returns (proceed_allowed, rendered_banner_or_message)."""
    # If bypass flag is set
    if allow_force or getattr(config, "force_deprecated", False):
        return True, "Deprecation check bypassed via --force-deprecated."

    policy = fetch_remote_version_policy(
        neon_url=getattr(config, "telemetry_url", None),
        auth_token=getattr(config, "telemetry_key", None),
    )

    is_allowed, status_code, msg = evaluate_version_support(current_version, policy)

    mode = policy.get("enforcement_mode", "block").strip().lower()

    if not is_allowed:
        banner = render_sunset_banner(current_version, policy)
        if mode == "block":
            return False, banner
        else:
            # Mode 'warn': print warning but allow user to proceed
            return True, banner

    return True, msg
