"""Automatic NAS & Cloud Backup (WebDAV / SMB / Local Network Share).

Enables automatic post-download synchronization and backup to network attached storage
(Synology, TrueNAS, QNAP, Nextcloud, Samba/SMB shares, and local mounted volumes).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
import shutil
import urllib.request
import urllib.error
from typing import Optional

LOGGER = logging.getLogger("universal_downloader.backup")


def upload_webdav(
    file_path: Path,
    webdav_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 30.0,
) -> bool:
    """Upload a local file to a WebDAV endpoint via HTTP PUT."""
    clean_url = webdav_url.replace("webdav://", "http://").rstrip("/")
    target_url = f"{clean_url}/{urllib.request.quote(file_path.name)}"

    LOGGER.info("Uploading %s to WebDAV: %s", file_path.name, target_url)

    req = urllib.request.Request(target_url, data=file_path.read_bytes(), method="PUT")
    req.add_header("Content-Type", "application/octet-stream")

    if username and password:
        creds = f"{username}:{password}".encode("utf-8")
        auth_header = f"Basic {base64.b64encode(creds).decode('ascii')}"
        req.add_header("Authorization", auth_header)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300 or resp.status == 201 or resp.status == 204
    except urllib.error.HTTPError as exc:
        LOGGER.warning("WebDAV upload failed HTTP %s: %s", exc.code, exc.reason)
        return False
    except Exception as exc:
        LOGGER.warning("WebDAV upload failed: %s", exc)
        return False


def copy_to_network_share(
    file_path: Path,
    target_dir: Path | str,
) -> Path:
    """Copy a file to a network share or local mount directory preserving timestamps."""
    dest_dir = Path(target_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / file_path.name

    LOGGER.info("Copying %s to network share: %s", file_path.name, dest_file)
    shutil.copy2(file_path, dest_file)
    return dest_file


def backup_media_file(
    file_path: Path | str,
    target: str,
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> bool:
    """Dispatch file backup based on target schema (WebDAV URL vs local/SMB path)."""
    source = Path(file_path).resolve()
    if not source.is_file():
        LOGGER.warning("Backup source file not found: %s", source)
        return False

    norm_target = (target or "").strip()
    if not norm_target:
        return False

    if norm_target.startswith("http://") or norm_target.startswith("https://") or norm_target.startswith("webdav://"):
        return upload_webdav(source, norm_target, username=username, password=password)

    # Local, mounted volume, UNC path (\\server\share), or SMB directory
    try:
        copy_to_network_share(source, norm_target)
        return True
    except Exception as exc:
        LOGGER.warning("Network share copy failed: %s", exc)
        return False
