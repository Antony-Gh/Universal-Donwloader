#!/usr/bin/env python3
"""
Automated PyInstaller build script for Universal Media Downloader.
Compiles downloader.py into dist/downloader.exe.
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    root_dir = Path(__file__).parent.resolve()
    os.chdir(root_dir)

    print("=== Universal Media Downloader Executable Builder ===")

    # 1. Check PyInstaller availability
    try:
        import PyInstaller
        print(f"✓ PyInstaller found: v{PyInstaller.__version__}")
    except ImportError:
        print("! PyInstaller is not installed. Installing via pip...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("✓ PyInstaller installed successfully.")
        except subprocess.CalledProcessError as exc:
            print(f"✗ Failed to install PyInstaller: {exc}", file=sys.stderr)
            return 1

    # 2. Run PyInstaller
    spec_path = root_dir / "downloader.spec"
    if not spec_path.exists():
        print(f"✗ Spec file not found at: {spec_path}", file=sys.stderr)
        return 1

    print(f"• Building executable from spec: {spec_path.name}...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path),
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"✗ PyInstaller build failed with exit code: {exc.returncode}", file=sys.stderr)
        return exc.returncode

    # 3. Verify output
    dist_exe = root_dir / "dist" / "downloader.exe"
    if dist_exe.exists():
        size_mb = dist_exe.stat().st_size / (1024 * 1024)
        print()
        print("═══════════════════════════════════════════════════════")
        print(f"✓ Build succeeded!")
        print(f"  Binary: {dist_exe}")
        print(f"  Size:   {size_mb:.2f} MB")
        print("═══════════════════════════════════════════════════════")
        return 0
    else:
        print(f"✗ Expected binary not found at: {dist_exe}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
