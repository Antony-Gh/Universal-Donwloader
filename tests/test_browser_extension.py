"""Tests for the standalone Manifest V3 Browser Extension (browser/extension/)."""

from __future__ import annotations

import json
from pathlib import Path

from universal_downloader.native_host import DEFAULT_FIREFOX_EXTENSIONS, HOST_NAME

EXT_DIR = Path(__file__).resolve().parent.parent / "browser" / "extension"


def test_extension_manifest_v3_structure() -> None:
    manifest_path = EXT_DIR / "manifest.json"
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert "nativeMessaging" in manifest["permissions"]
    assert "contextMenus" in manifest["permissions"]
    assert "activeTab" in manifest["permissions"]
    assert "scripting" in manifest["permissions"]

    # Service worker and popup files exist
    bg_script = EXT_DIR / manifest["background"]["service_worker"]
    popup_html = EXT_DIR / manifest["action"]["default_popup"]
    popup_js = EXT_DIR / "popup.js"
    assert bg_script.is_file()
    assert popup_html.is_file()
    assert popup_js.is_file()

    # Firefox gecko extension ID matches DEFAULT_FIREFOX_EXTENSIONS in native_host.py
    gecko_id = manifest["browser_specific_settings"]["gecko"]["id"]
    assert gecko_id in DEFAULT_FIREFOX_EXTENSIONS


def test_extension_scripts_reference_matching_native_host() -> None:
    bg_text = (EXT_DIR / "background.js").read_text(encoding="utf-8")
    popup_text = (EXT_DIR / "popup.js").read_text(encoding="utf-8")

    assert HOST_NAME in bg_text
    assert HOST_NAME in popup_text
    assert "downloader://" in bg_text
    assert "downloader://" in popup_text
