#!/usr/bin/env python3
"""
One-click Build, Packaging, and GitHub Release Publishing Orchestrator.

Compiles:
  - Python Backend: Standalone executable via PyInstaller
  - C# Avalonia Frontend: Self-contained single-file binaries for Windows (x64), Linux (x64), and macOS (x64 & ARM64)
  - C# WPF Frontend: Native Windows application

Packages:
  - UniversalDownloader-<version>-windows-x64.zip
  - UniversalDownloader-<version>-linux-x64.tar.gz
  - UniversalDownloader-<version>-macos-x64.tar.gz
  - UniversalDownloader-<version>-macos-arm64.tar.gz
  - SHA256SUMS.txt

Publishes:
  - Creates git release tag and pushes to GitHub
  - Publishes a full GitHub Release via `gh` CLI or GitHub REST API
  - Triggers automated GitHub Actions matrix build for cloud-native compilation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent
RELEASES_DIR = ROOT_DIR / "releases"
BUILD_TMP_DIR = ROOT_DIR / "build_temp"

# ANSI Terminal Colors
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def print_step(title: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.CYAN}==> {title}{Colors.RESET}")


def print_success(msg: str) -> None:
    print(f"{Colors.GREEN}[✓] {msg}{Colors.RESET}")


def print_warning(msg: str) -> None:
    print(f"{Colors.YELLOW}[!] {msg}{Colors.RESET}")


def print_error(msg: str) -> None:
    print(f"{Colors.RED}[✗] {msg}{Colors.RESET}")


def run_command(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a system command and stream output."""
    cmd_str = " ".join(cmd)
    print(f"  {Colors.BOLD}$ {cmd_str}{Colors.RESET}")
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT_DIR), text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}: {cmd_str}")
    return proc


def detect_repo_info() -> Tuple[str, str]:
    """Extract owner and repository name from git remote origin."""
    try:
        proc = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True)
        url = proc.stdout.strip()
        # Matches https://github.com/owner/repo.git or git@github.com:owner/repo.git
        match = re.search(r"github\.com[/:](?P<owner>[^/]+)/(?P<repo>[^/.]+)", url)
        if match:
            return match.group("owner"), match.group("repo")
    except Exception as exc:
        print_warning(f"Could not automatically detect git remote origin: {exc}")
    return "Antony-Gh", "Universal-Donwloader"


def get_default_version() -> str:
    """Detect version from pyproject.toml or universal_downloader."""
    pyproj = ROOT_DIR / "pyproject.toml"
    if pyproj.exists():
        text = pyproj.read_text(encoding="utf-8")
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            return match.group(1).lstrip("v")
    return "1.1.0"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_python_backend() -> Optional[Path]:
    """Build standalone Python executable via PyInstaller for the current host OS."""
    print_step("Compiling Python Backend with PyInstaller")
    try:
        # Check if pyinstaller is installed
        import PyInstaller
    except ImportError:
        print("  Installing PyInstaller...")
        run_command([sys.executable, "-m", "pip", "install", "pyinstaller", "pillow"])

    spec_file = ROOT_DIR / "downloader.spec"
    if not spec_file.exists():
        raise FileNotFoundError(f"Missing spec file: {spec_file}")

    run_command(["pyinstaller", "downloader.spec", "--noconfirm"])

    exe_name = "downloader.exe" if sys.platform.startswith("win") else "downloader"
    dist_bin = ROOT_DIR / "dist" / exe_name
    if dist_bin.exists():
        print_success(f"Built Python standalone binary: {dist_bin} ({dist_bin.stat().st_size / 1024 / 1024:.1f} MB)")
        return dist_bin

    print_warning(f"Compiled binary not found at expected location: {dist_bin}")
    return None


def ensure_release_ffmpeg() -> None:
    """Stage static FFmpeg into dist/ for zero-friction turnkey releases."""
    print_step("Checking Standalone FFmpeg Engine")
    dist_dir = ROOT_DIR / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    exe_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    probe_name = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"

    if (dist_dir / exe_name).exists():
        print_success(f"FFmpeg binary ready at {dist_dir / exe_name}")
        return

    try:
        from universal_downloader.ffmpeg_manager import find_ffmpeg, ensure_ffmpeg
        found = find_ffmpeg() or ensure_ffmpeg(auto_download=True)
        if found and found.exists():
            shutil.copy2(found, dist_dir / exe_name)
            probe = found.with_name(probe_name)
            if probe.exists():
                shutil.copy2(probe, dist_dir / probe_name)
            print_success(f"Staged {exe_name} into dist/ for embedded single-file packaging.")
        else:
            print_warning("FFmpeg not staged locally; runtime will auto-download when needed.")
    except Exception as exc:
        print_warning(f"FFmpeg staging skipped: {exc}")


def publish_dotnet_target(project_path: Path, rid: str, output_dir: Path) -> bool:
    """Publish a self-contained, single-file .NET 9 application for a target RID with fallback."""
    print(f"  Building {project_path.stem} for {rid}...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Try single-file self-contained publish
    cmd = [
        "dotnet",
        "publish",
        str(project_path),
        "-c", "Release",
        "-r", rid,
        "--self-contained", "true",
        "-p:PublishSingleFile=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-o", str(output_dir),
    ]

    try:
        proc = run_command(cmd, check=False)
        if proc.returncode == 0:
            print_success(f"Published {project_path.stem} [{rid}] -> {output_dir}")
            return True
    except Exception as exc:
        print_warning(f"Self-contained publish for {rid} encountered error: {exc}")

    # 2. Fallback to framework-dependent publish
    print(f"  Attempting framework-dependent publish for {rid}...")
    fallback_cmd = [
        "dotnet",
        "publish",
        str(project_path),
        "-c", "Release",
        "-r", rid,
        "--self-contained", "false",
        "-o", str(output_dir),
    ]

    try:
        proc = run_command(fallback_cmd, check=False)
        if proc.returncode == 0:
            print_success(f"Published {project_path.stem} (framework-dependent) [{rid}] -> {output_dir}")
            return True
    except Exception as exc:
        print_warning(f"Fallback publish failed for {rid}: {exc}")

    print_warning(f"Note: Native binary for {rid} will be compiled automatically in the cloud via GitHub Actions runners.")
    return False


def create_linux_launcher_script(dest_path: Path) -> None:
    """Create a helper shell script for Linux distribution."""
    script_content = """#!/usr/bin/env bash
# Universal Media Downloader Linux Launcher
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure executables have execute permission
chmod +x "$DIR/UniversalDownloader.Avalonia" 2>/dev/null || true
if [ -f "$DIR/downloader" ]; then
    chmod +x "$DIR/downloader" 2>/dev/null || true
fi

# Run the GUI application
exec "$DIR/UniversalDownloader.Avalonia" "$@"
"""
    dest_path.write_text(script_content, encoding="utf-8")


def package_windows_release(version: str) -> List[Path]:
    """Create single-file Windows executable and clean distribution zip."""
    print_step("Packaging Windows x64 Standalone Executable")
    avalonia_dir = BUILD_TMP_DIR / "win-x64-avalonia"
    
    # Locate built Windows single-file executable
    candidate_exe = None
    for name in ["UniversalDownloader.exe", "UniversalDownloader.Avalonia.exe"]:
        if (avalonia_dir / name).exists():
            candidate_exe = avalonia_dir / name
            break

    if not candidate_exe and avalonia_dir.exists():
        for item in avalonia_dir.glob("*.exe"):
            candidate_exe = item
            break

    results: List[Path] = []
    if candidate_exe and candidate_exe.exists():
        # 1. Output the single standalone .exe directly for one-click downloading!
        direct_exe = RELEASES_DIR / "UniversalDownloader.exe"
        shutil.copy2(candidate_exe, direct_exe)
        print_success(f"Generated Standalone Windows Executable: {direct_exe.name} ({direct_exe.stat().st_size / 1024 / 1024:.1f} MB)")
        results.append(direct_exe)

        # 2. Also package clean zip containing only UniversalDownloader.exe and documentation
        pkg_name = f"UniversalDownloader-v{version}-windows-x64"
        staging = BUILD_TMP_DIR / pkg_name
        staging.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_exe, staging / "UniversalDownloader.exe")
        if (ROOT_DIR / "README.md").exists():
            shutil.copy2(ROOT_DIR / "README.md", staging / "README.md")

        zip_path = RELEASES_DIR / f"{pkg_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staging):
                for file in files:
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(staging)
                    zf.write(full_path, arcname)

        print_success(f"Created {zip_path.name} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
        results.append(zip_path)

    return results


def package_tar_release(platform_name: str, rid: str, version: str) -> List[Path]:
    """Create Linux or macOS GUI distribution package and standalone binary."""
    print_step(f"Packaging {platform_name} ({rid}) GUI Distribution")
    pkg_name = f"UniversalDownloader-v{version}-{platform_name}"
    staging = BUILD_TMP_DIR / pkg_name
    staging.mkdir(parents=True, exist_ok=True)

    rid_dir = BUILD_TMP_DIR / rid
    candidate_bin = None
    for name in ["UniversalDownloader", "UniversalDownloader.Avalonia"]:
        if (rid_dir / name).exists():
            candidate_bin = rid_dir / name
            break

    results: List[Path] = []
    if candidate_bin and candidate_bin.exists():
        # Copy GUI binary into staging
        dest_bin = staging / "UniversalDownloader"
        shutil.copy2(candidate_bin, dest_bin)
        try:
            dest_bin.chmod(0o755)
        except Exception:
            pass

        # Also copy runtime dependencies / dylibs if present
        for item in rid_dir.glob("*.dylib"):
            shutil.copy2(item, staging / item.name)

        # Standalone binary for Linux
        if "linux" in rid:
            direct_bin = RELEASES_DIR / "UniversalDownloader-linux-x64"
            shutil.copy2(candidate_bin, direct_bin)
            try:
                direct_bin.chmod(0o755)
            except Exception:
                pass
            print_success(f"Generated Standalone Linux Executable: {direct_bin.name} ({direct_bin.stat().st_size / 1024 / 1024:.1f} MB)")
            results.append(direct_bin)

    # Launcher script on Linux
    if "linux" in rid:
        create_linux_launcher_script(staging / "run.sh")

    # Documentation and assets
    if (ROOT_DIR / "README.md").exists():
        shutil.copy2(ROOT_DIR / "README.md", staging / "README.md")
    if (ROOT_DIR / "assets").exists():
        shutil.copytree(ROOT_DIR / "assets", staging / "assets", dirs_exist_ok=True)

    # Create tar.gz
    tar_path = RELEASES_DIR / f"{pkg_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(staging, arcname=pkg_name)

    print_success(f"Created {tar_path.name} ({tar_path.stat().st_size / 1024 / 1024:.1f} MB)")
    results.append(tar_path)
    return results


def generate_checksums(archives: List[Path]) -> Path:
    """Generate SHA256SUMS.txt file."""
    print_step("Generating SHA-256 Checksums")
    checksum_file = RELEASES_DIR / "SHA256SUMS.txt"
    lines = []
    for archive in archives:
        h = compute_sha256(archive)
        lines.append(f"{h}  {archive.name}")
        print(f"  {h[:16]}...  {archive.name}")

    checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print_success(f"Wrote checksums to: {checksum_file}")
    return checksum_file


def publish_github_release(
    owner: str,
    repo: str,
    tag: str,
    release_name: str,
    notes: str,
    files: List[Path],
    token: Optional[str] = None,
    draft: bool = False,
    prerelease: bool = False,
) -> bool:
    """Publish release using gh CLI or GitHub REST API."""
    print_step(f"Publishing Release to GitHub ({owner}/{repo} @ {tag})")

    # 1. Ensure git tag is pushed
    try:
        run_command(["git", "tag", "-a", tag, "-m", release_name], check=False)
        print("  Pushing git tag to remote origin...")
        run_command(["git", "push", "origin", tag], check=False)
    except Exception as exc:
        print_warning(f"Git tag push skipped or warning: {exc}")

    # 2. Try GitHub CLI first if available
    if shutil.which("gh"):
        gh_auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if gh_auth.returncode == 0:
            print("  Using authenticated GitHub CLI (gh)...")
            cmd = ["gh", "release", "create", tag]
            for f in files:
                cmd.append(str(f))
            cmd.extend(["--title", release_name, "--notes", notes])
            if draft: cmd.append("--draft")
            if prerelease: cmd.append("--prerelease")

            try:
                run_command(cmd)
                print_success(f"Successfully published release {tag} via GitHub CLI!")
                print(f"  View online: https://github.com/{owner}/{repo}/releases/tag/{tag}")
                return True
            except Exception as exc:
                print_warning(f"gh CLI release creation encountered an issue: {exc}")

    # 3. Fallback to GitHub REST API with Token
    auth_token = token or os.environ.get("GITHUB_TOKEN")
    if auth_token:
        print("  Using GitHub REST API with authorization token...")
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        payload = {
            "tag_name": tag,
            "name": release_name,
            "body": notes,
            "draft": draft,
            "prerelease": prerelease,
        }

        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Universal-Downloader-Release-Bot",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                upload_url = res_data["upload_url"].split("{")[0]
                release_html = res_data.get("html_url", f"https://github.com/{owner}/{repo}/releases/tag/{tag}")
                print_success(f"Created release container at {release_html}")

            # Upload each asset file
            for f in files:
                print(f"  Uploading asset: {f.name}...")
                upload_endpoint = f"{upload_url}?name={f.name}"
                with open(f, "rb") as asset_data:
                    upload_req = urllib.request.Request(
                        upload_endpoint,
                        data=asset_data.read(),
                        headers={
                            "Authorization": f"Bearer {auth_token}",
                            "Content-Type": "application/octet-stream",
                            "User-Agent": "Universal-Downloader-Release-Bot",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(upload_req):
                        print_success(f"Uploaded {f.name}")

            print_success(f"All assets uploaded! Release live at: {release_html}")
            return True
        except urllib.error.HTTPError as http_err:
            print_error(f"GitHub API Error ({http_err.code}): {http_err.read().decode('utf-8')}")
        except Exception as exc:
            print_error(f"Failed to publish via GitHub API: {exc}")

    # 4. Manual Fallback Instructions
    print_warning("Could not automatically upload release due to missing GitHub authorization.")
    print(f"\n{Colors.BOLD}You can publish the release manually in seconds:{Colors.RESET}")
    print(f"1. Open: {Colors.CYAN}https://github.com/{owner}/{repo}/releases/new?tag={tag}{Colors.RESET}")
    print(f"2. Set Title: {Colors.BOLD}{release_name}{Colors.RESET}")
    print(f"3. Drag & Drop the built archives from:")
    for f in files:
        print(f"   - {f.resolve()}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-click Build, Packaging, and GitHub Release Publisher for Universal Media Downloader"
    )
    parser.add_argument("-v", "--version", default=None, help="Release version (e.g. 1.1.0 or v1.1.0)")
    parser.add_argument("--no-publish", action="store_true", help="Build local packages without publishing to GitHub")
    parser.add_argument("--token", default=None, help="GitHub Personal Access Token for API publishing")
    parser.add_argument("--draft", action="store_true", help="Publish release as a draft")
    parser.add_argument("--prerelease", action="store_true", help="Mark release as a pre-release")
    args = parser.parse_args()

    version = (args.version or get_default_version()).lstrip("v")
    tag = f"v{version}"
    owner, repo = detect_repo_info()

    print(f"{Colors.BOLD}{Colors.GREEN}")
    print("=" * 70)
    print(f"  Universal Media Downloader — Build & Release Orchestrator")
    print(f"  Target Version: {tag} | Repository: {owner}/{repo}")
    print("=" * 70)
    print(f"{Colors.RESET}")

    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_TMP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Build Standalone Python Backend
    python_bin = build_python_backend()
    ensure_release_ffmpeg()

    # 2. Build C# Avalonia for all platforms
    avalonia_proj = ROOT_DIR / "src" / "UniversalDownloader.Avalonia" / "UniversalDownloader.Avalonia.csproj"
    wpf_proj = ROOT_DIR / "src" / "UniversalDownloader.App" / "UniversalDownloader.App.csproj"

    print_step("Publishing Self-Contained .NET 9 Frontend Executables")
    # Windows
    publish_dotnet_target(avalonia_proj, "win-x64", BUILD_TMP_DIR / "win-x64-avalonia")
    if sys.platform.startswith("win"):
        publish_dotnet_target(wpf_proj, "win-x64", BUILD_TMP_DIR / "win-x64-wpf")

    # Linux & macOS
    publish_dotnet_target(avalonia_proj, "linux-x64", BUILD_TMP_DIR / "linux-x64")
    publish_dotnet_target(avalonia_proj, "osx-x64", BUILD_TMP_DIR / "osx-x64")
    publish_dotnet_target(avalonia_proj, "osx-arm64", BUILD_TMP_DIR / "osx-arm64")

    # 3. Create Distribution Archives & Standalone Executables
    archives: List[Path] = []
    archives.extend(package_windows_release(version))
    archives.extend(package_tar_release("linux-x64", "linux-x64", version))
    archives.extend(package_tar_release("macos-arm64", "osx-arm64", version))
    archives.extend(package_tar_release("macos-x64", "osx-x64", version))

    # 4. Generate SHA256 Checksums
    checksum_file = generate_checksums(archives)
    all_release_files = archives + [checksum_file]

    # Summary
    print_step("Build Summary & Generated Release Files")
    for f in all_release_files:
        size_str = f"{f.stat().st_size / 1024 / 1024:.2f} MB" if f.name.endswith((".zip", ".tar.gz", ".exe")) or f.stat().st_size > 1024 * 1024 else f"{f.stat().st_size} bytes"
        print(f"  • {Colors.BOLD}{f.name:<45}{Colors.RESET} ({size_str})")

    # 5. Publish to GitHub
    if not args.no_publish:
        release_notes = (
            f"## Universal Media Downloader {tag}\n\n"
            f"Production-grade media downloader with native high-speed C# GUI frontends and a Python media engine.\n\n"
            f"### Standalone Downloads (Direct Click-and-Run):\n"
            f"- **Windows (One Single .exe)**: [`UniversalDownloader.exe`](https://github.com/{owner}/{repo}/releases/download/{tag}/UniversalDownloader.exe)\n"
            f"  *Pure single executable file. No zip, no installer, no Python or .NET runtime installation required.*\n"
            f"- **Linux (Full GUI Executable)**: [`UniversalDownloader-v{version}-linux-x64.tar.gz`](https://github.com/{owner}/{repo}/releases/download/{tag}/UniversalDownloader-v{version}-linux-x64.tar.gz) or standalone binary `UniversalDownloader-linux-x64`\n"
            f"  *Full Avalonia GUI running on Wayland and X11.*\n"
            f"- **macOS (Apple Silicon M-series)**: [`UniversalDownloader-v{version}-macos-arm64.tar.gz`](https://github.com/{owner}/{repo}/releases/download/{tag}/UniversalDownloader-v{version}-macos-arm64.tar.gz)\n"
            f"- **macOS (Intel x64)**: [`UniversalDownloader-v{version}-macos-x64.tar.gz`](https://github.com/{owner}/{repo}/releases/download/{tag}/UniversalDownloader-v{version}-macos-x64.tar.gz)\n\n"
            f"### Features:\n"
            f"- **Cross-Platform C# GUI**: Avalonia 11 UI running smoothly on Windows, Linux, and macOS\n"
            f"- **Embedded Media Engine**: Multi-fragment concurrent streaming, time-range slicing, codec selection\n"
            f"- **SQLite Download History**: Search, play downloaded media, and reveal files in Explorer/Finder/Nautilus\n"
            f"- **Desktop Notifications & Watcher**: System clipboard polling and completion alerts across all platforms\n"
        )
        publish_github_release(
            owner=owner,
            repo=repo,
            tag=tag,
            release_name=f"Universal Media Downloader {tag}",
            notes=release_notes,
            files=all_release_files,
            token=args.token,
            draft=args.draft,
            prerelease=args.prerelease,
        )
    else:
        print_success("Built release packages locally (--no-publish specified).")


if __name__ == "__main__":
    main()
