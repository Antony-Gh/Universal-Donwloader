#!/usr/bin/env python3
"""
Build the Windows MSI installer for Universal Media Downloader using WiX Toolset v5.

Reads app name, version, manufacturer, GitHub URL, and fixed MSI UpgradeCode directly
from the shared app_config.json file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent
APP_CONFIG_FILE = ROOT_DIR / "app_config.json"


def load_config() -> dict:
    if APP_CONFIG_FILE.exists():
        return json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def normalize_msi_version(raw_version: str) -> str:
    """WiX MSI versions require numeric Major.Minor.Build[.Revision] (e.g. 2.2.0)."""
    cleaned = raw_version.strip().lstrip("v").split("-", 1)[0]
    parts = [p for p in cleaned.split(".") if p.isdigit()]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:4])


def find_wix_binary() -> str | None:
    found = shutil.which("wix")
    if found:
        return found
    dotnet_tool = Path.home() / ".dotnet" / "tools" / "wix.exe"
    if dotnet_tool.exists():
        return str(dotnet_tool)
    return None


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_msi(exe_path: Path, output_path: Path, version_override: str | None = None) -> Path:
    wix = find_wix_binary()
    if not wix:
        raise RuntimeError(
            "WiX Toolset v5 CLI ('wix') not found.\n"
            "Install it once with:\n"
            "  dotnet tool install --global wix --version 5.0.2\n"
            "  wix extension add -g WixToolset.UI.wixext/5.0.2"
        )

    if not exe_path.exists():
        raise FileNotFoundError(f"Executable not found: {exe_path}")

    cfg = load_config()
    desktop_cfg = cfg.get("desktop", {}) if isinstance(cfg.get("desktop"), dict) else {}

    app_name = str(cfg.get("app_name") or "Universal Media Downloader")
    version = normalize_msi_version(version_override or str(cfg.get("version_name") or "3.1.0"))
    owner = str(cfg.get("github_owner") or "Antony-Gh")
    repo = str(cfg.get("github_repo") or "Universal-Donwloader")
    repo_url = f"https://github.com/{owner}/{repo}"
    upgrade_code = str(desktop_cfg.get("msi_upgrade_code") or "8F4B9A2C-6E1D-4A3F-9C8B-2E5A7D1F4B90")

    wxs_path = SCRIPT_DIR / "Package.wxs"
    license_rtf = SCRIPT_DIR / "License.rtf"
    icon_path = ROOT_DIR / "src" / "UniversalDownloader.Avalonia" / "Assets" / "app-icon.ico"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        wix,
        "build",
        str(wxs_path),
        "-ext", "WixToolset.UI.wixext",
        "-arch", "x64",
        "-d", f"AppName={app_name}",
        "-d", f"AppVersion={version}",
        "-d", f"Manufacturer={owner}",
        "-d", f"UpgradeCode={upgrade_code}",
        "-d", f"RepoUrl={repo_url}",
        "-d", f"ExePath={exe_path.resolve()}",
        "-d", f"IconPath={icon_path.resolve()}",
        "-d", f"LicenseRtfPath={license_rtf.resolve()}",
        "-o", str(output_path.resolve()),
    ]

    print(f"Building MSI installer v{version} using WiX...")
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"WiX build failed with exit code {proc.returncode}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    digest = compute_sha256(output_path)
    print(f"[OK] Built MSI: {output_path} ({size_mb:.2f} MB)")
    print(f"     SHA-256:   {digest}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows MSI installer for Universal Media Downloader")
    parser.add_argument(
        "--exe",
        type=Path,
        default=ROOT_DIR / "releases" / "UniversalDownloader.exe",
        help="Path to the published UniversalDownloader.exe binary",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "releases" / "UniversalDownloader-Setup-x64.msi",
        help="Output .msi file path",
    )
    parser.add_argument("--version", default=None, help="Override MSI version (defaults to app_config.json)")
    args = parser.parse_args()

    try:
        build_msi(args.exe, args.out, args.version)
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
