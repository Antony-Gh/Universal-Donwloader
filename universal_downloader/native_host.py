"""Browser Native Messaging Host (CoApp) protocol implementation.

Implements the standard Chrome / Edge / Firefox Native Messaging stdio protocol
(32-bit unsigned little-endian length prefix followed by UTF-8 JSON payload),
allowing browser extensions to communicate directly with Universal Media Downloader.
"""

from __future__ import annotations

import json
import os
import platform
import struct
import sys
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional

from universal_downloader import __version__
from universal_downloader.models import AppConfig
from universal_downloader.search import search_youtube

HOST_NAME = "com.universaldownloader.coapp"
HOST_DESCRIPTION = "Universal Media Downloader Companion Host"
MAX_MESSAGE_BYTES = 10 * 1024 * 1024  # 10 MB safety cap

DEFAULT_CHROME_ORIGINS = [
    "chrome-extension://universaldownloaderextension/",
]
DEFAULT_FIREFOX_EXTENSIONS = [
    "universal-downloader@antony-gh.github.io",
]


def read_native_message(stream: Optional[BinaryIO] = None) -> Optional[dict[str, Any]]:
    """Read a single length-prefixed JSON message from a binary stream.

    Returns None on clean EOF.
    """
    src = stream or sys.stdin.buffer
    raw_length = src.read(4)
    if not raw_length or len(raw_length) < 4:
        return None

    (message_length,) = struct.unpack("<I", raw_length)
    if message_length == 0:
        return {}
    if message_length > MAX_MESSAGE_BYTES:
        raise ValueError(f"Native message exceeds maximum size ({message_length} bytes).")

    payload_bytes = src.read(message_length)
    if len(payload_bytes) < message_length:
        return None

    data = json.loads(payload_bytes.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Native message payload must be a JSON object.")
    return data


def write_native_message(payload: dict[str, Any], stream: Optional[BinaryIO] = None) -> None:
    """Write a length-prefixed JSON message to a binary stream."""
    dst = stream or sys.stdout.buffer
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    dst.write(struct.pack("<I", len(encoded)))
    dst.write(encoded)
    dst.flush()


def handle_native_command(
    message: dict[str, Any],
    base_config: AppConfig,
    engine_factory: Optional[Callable[[AppConfig], Any]] = None,
) -> dict[str, Any]:
    """Dispatch a single Native Messaging request dict and return a JSON-serializable reply."""
    action = str(message.get("action") or "").strip().lower()

    if action == "ping":
        return {
            "ok": True,
            "host": HOST_NAME,
            "version": __version__,
            "platform": platform.system(),
        }

    if action == "search":
        query = str(message.get("query") or "").strip()
        limit = int(message.get("limit") or 10)
        if not query:
            return {"ok": False, "error": "Missing 'query' field."}
        try:
            results = search_youtube(query, limit=limit, proxy=base_config.proxy, timeout=base_config.timeout)
            return {"ok": True, "query": query, "results": results}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if action in {"metadata", "download"}:
        url = str(message.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "Missing 'url' field."}

        if engine_factory is None:
            from universal_downloader.engine import DownloadEngine

            engine_factory = DownloadEngine

        cfg = AppConfig(
            output_dir=Path(message["output_dir"]).expanduser() if message.get("output_dir") else base_config.output_dir,
            quality=str(message.get("quality") or base_config.quality),
            audio_only=bool(message.get("audio_only", base_config.audio_only)),
            audio_format=str(message.get("audio_format") or base_config.audio_format),
            organize=str(message.get("organize") or base_config.organize),
            clean_filenames=bool(message.get("clean_filenames", base_config.clean_filenames)),
            proxy=base_config.proxy,
            cookies_file=base_config.cookies_file,
            cookies_from_browser=base_config.cookies_from_browser,
            json_output=True,
            json_stream=False,
        )
        engine = engine_factory(cfg)

        try:
            if action == "metadata":
                info = engine.inspect(url)
                return {
                    "ok": True,
                    "url": url,
                    "title": info.get("title"),
                    "uploader": info.get("uploader") or info.get("channel"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                }

            result = engine.download(url)
            return {
                "ok": bool(result.success),
                "url": result.url,
                "files": [str(p) for p in result.files],
                "title": (result.metadata or {}).get("title"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": f"Unknown action: {action or '<empty>'}"}


def run_native_host(
    config: AppConfig,
    in_stream: Optional[BinaryIO] = None,
    out_stream: Optional[BinaryIO] = None,
    engine_factory: Optional[Callable[[AppConfig], Any]] = None,
) -> int:
    """Run the stdio Native Messaging event loop until stdin closes."""
    while True:
        try:
            msg = read_native_message(in_stream)
        except Exception as exc:
            write_native_message({"ok": False, "error": str(exc)}, out_stream)
            continue

        if msg is None:
            return 0

        reply = handle_native_command(msg, config, engine_factory=engine_factory)
        if "id" in msg:
            reply["id"] = msg["id"]
        write_native_message(reply, out_stream)


def build_native_host_manifest(
    host_path: Path,
    browser: str = "chrome",
    allowed_origins: Optional[list[str]] = None,
    allowed_extensions: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Construct a Chrome/Edge or Firefox Native Messaging host manifest dictionary."""
    manifest: dict[str, Any] = {
        "name": HOST_NAME,
        "description": HOST_DESCRIPTION,
        "path": str(host_path),
        "type": "stdio",
    }
    if browser.lower() == "firefox":
        manifest["allowed_extensions"] = allowed_extensions or list(DEFAULT_FIREFOX_EXTENSIONS)
    else:
        manifest["allowed_origins"] = allowed_origins or list(DEFAULT_CHROME_ORIGINS)
    return manifest


def _get_manifest_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "UniversalDownloader" / "NativeMessaging"
    return Path.home() / ".config" / "universal-downloader" / "native-messaging"


def _create_launcher_script(manifest_dir: Path, executable_path: Optional[Path] = None) -> Path:
    """Create a standalone wrapper executable/script invoking `--native-host`."""
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if executable_path and executable_path.suffix.lower() == ".exe":
        target_cmd = f'"{executable_path.resolve()}" --native-host'
    else:
        script_path = (executable_path or (Path(__file__).parent.parent / "downloader.py")).resolve()
        target_cmd = f'"{sys.executable}" "{script_path}" --native-host'

    if sys.platform == "win32":
        launcher = manifest_dir / "universal_downloader_host.bat"
        launcher.write_text(f"@echo off\r\n{target_cmd}\r\n", encoding="utf-8")
        return launcher

    launcher = manifest_dir / "universal_downloader_host.sh"
    launcher.write_text(f"#!/usr/bin/env sh\nexec {target_cmd}\n", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def register_native_host(
    executable_path: Optional[Path] = None,
    allowed_origins: Optional[list[str]] = None,
    allowed_extensions: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """Register Native Messaging host manifests for Chrome, Edge, and Firefox."""
    try:
        manifest_dir = _get_manifest_dir()
        launcher = _create_launcher_script(manifest_dir, executable_path)

        chrome_manifest = build_native_host_manifest(launcher, "chrome", allowed_origins=allowed_origins)
        firefox_manifest = build_native_host_manifest(launcher, "firefox", allowed_extensions=allowed_extensions)

        chrome_path = manifest_dir / f"{HOST_NAME}.chrome.json"
        firefox_path = manifest_dir / f"{HOST_NAME}.firefox.json"
        chrome_path.write_text(json.dumps(chrome_manifest, indent=2), encoding="utf-8")
        firefox_path.write_text(json.dumps(firefox_manifest, indent=2), encoding="utf-8")

        if sys.platform == "win32":
            import winreg

            reg_targets = [
                (rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}", str(chrome_path)),
                (rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}", str(chrome_path)),
                (rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}", str(firefox_path)),
            ]
            for subkey, manifest_file in reg_targets:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_file)
            return True, f"Registered Native Messaging host ({HOST_NAME}) for Chrome, Edge, and Firefox."

        # Linux / macOS manifest locations
        if sys.platform == "darwin":
            targets = [
                (Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts", chrome_manifest),
                (Path.home() / "Library/Application Support/Microsoft Edge/NativeMessagingHosts", chrome_manifest),
                (Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts", firefox_manifest),
            ]
        else:
            targets = [
                (Path.home() / ".config/google-chrome/NativeMessagingHosts", chrome_manifest),
                (Path.home() / ".config/microsoft-edge/NativeMessagingHosts", chrome_manifest),
                (Path.home() / ".mozilla/native-messaging-hosts", firefox_manifest),
            ]
        for directory, manifest in targets:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{HOST_NAME}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return True, f"Registered Native Messaging host ({HOST_NAME}) in user browser directories."
    except Exception as exc:
        return False, f"Failed to register Native Messaging host: {exc}"


def unregister_native_host() -> tuple[bool, str]:
    """Remove Native Messaging host registrations and manifests."""
    try:
        if sys.platform == "win32":
            import winreg

            for subkey in (
                rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
                rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
                rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}",
            ):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
                except FileNotFoundError:
                    pass
        else:
            dirs = (
                [
                    Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts",
                    Path.home() / "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
                    Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts",
                ]
                if sys.platform == "darwin"
                else [
                    Path.home() / ".config/google-chrome/NativeMessagingHosts",
                    Path.home() / ".config/microsoft-edge/NativeMessagingHosts",
                    Path.home() / ".mozilla/native-messaging-hosts",
                ]
            )
            for directory in dirs:
                candidate = directory / f"{HOST_NAME}.json"
                if candidate.exists():
                    candidate.unlink()

        manifest_dir = _get_manifest_dir()
        for fname in (
            f"{HOST_NAME}.chrome.json",
            f"{HOST_NAME}.firefox.json",
            "universal_downloader_host.bat",
            "universal_downloader_host.sh",
        ):
            fpath = manifest_dir / fname
            if fpath.exists():
                fpath.unlink()

        return True, f"Unregistered Native Messaging host ({HOST_NAME})."
    except Exception as exc:
        return False, f"Failed to unregister Native Messaging host: {exc}"
