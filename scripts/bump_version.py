#!/usr/bin/env python3
"""
Update the version number (and version code) across all project files.

Single-purpose script: ONLY updates version strings and version codes across
Desktop (.NET / Avalonia / WiX MSI), Android (Gradle / README), Python,
Browser Extension (manifest.json), app_config.json, and GitHub Actions release workflow.

Examples:
    python scripts/bump_version.py 2.3.0
    python scripts/bump_version.py 2.3.0 --code 230
    python scripts/bump_version.py --patch
    python scripts/bump_version.py --minor
    python scripts/bump_version.py --major
    python scripts/bump_version.py --sync
    python scripts/bump_version.py 2.3.0 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_semver(raw: str) -> Tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(raw.strip())
    if not match:
        raise ValueError(f"Invalid version '{raw}'. Expected format: MAJOR.MINOR.PATCH (e.g. 2.3.0)")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def compute_version_code(major: int, minor: int, patch: int, current_code: int = 0) -> int:
    """Compute a strictly increasing integer version_code (Android requires monotonic increase)."""
    formula_code = major * 100 + minor * 10 + patch
    return max(formula_code, current_code + 1) if current_code > 0 else formula_code


def read_current_version(root: Path = ROOT_DIR) -> Tuple[str, int]:
    cfg_path = root / "app_config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Missing {cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    version = str(data.get("version_name") or "1.0.0").lstrip("v")
    code = int(data.get("version_code") or 100)
    return version, code


def _apply_regex_replacements(
    text: str,
    rules: list[Tuple[str, str]],
) -> str:
    updated = text
    for pattern, replacement in rules:
        updated = re.sub(pattern, replacement, updated, flags=re.MULTILINE)
    return updated


def update_all_versions(
    new_version: str,
    new_code: int,
    root: Path = ROOT_DIR,
    dry_run: bool = False,
) -> list[Tuple[str, bool]]:
    """Update version_name and version_code across every project file. Returns (rel_path, changed)."""
    v = new_version.lstrip("v")
    c = str(new_code)

    # 1. app_config.json (structured JSON update)
    def update_app_config(text: str) -> str:
        data = json.loads(text)
        data["version_name"] = v
        data["version_code"] = new_code
        return json.dumps(data, indent=2) + "\n"

    targets: list[Tuple[str, Callable[[str], str]]] = [
        ("app_config.json", update_app_config),
        (
            "pyproject.toml",
            lambda t: _apply_regex_replacements(
                t,
                [(r'^(version\s*=\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            "universal_downloader/__init__.py",
            lambda t: _apply_regex_replacements(
                t,
                [
                    (r'(__version__\s*:\s*str\s*=\s*str\(APP_CONFIG\.get\("version_name"\)\s*or\s*")[^"]+("\))', rf'\g<1>{v}\g<2>'),
                    (r'(__version_code__\s*:\s*int\s*=\s*int\(APP_CONFIG\.get\("version_code"\)\s*or\s*)\d+(\))', rf'\g<1>{c}\g<2>'),
                ],
            ),
        ),
        (
            "build_and_publish.py",
            lambda t: _apply_regex_replacements(
                t,
                [(r'(def get_default_version\(\)[\s\S]*?return\s+")[^"]+(")', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            "installer/windows/build_msi.py",
            lambda t: _apply_regex_replacements(
                t,
                [(r'(cfg\.get\("version_name"\)\s*or\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            "src/Directory.Build.props",
            lambda t: _apply_regex_replacements(
                t,
                [
                    (r"(<Version\s+Condition=\"'\$\(Version\)'\s*==\s*''\">)[^<]+(</Version>)", rf"\g<1>{v}\g<2>"),
                    (r"(<AppVersionCode\s+Condition=\"'\$\(AppVersionCode\)'\s*==\s*''\">)\d+(</AppVersionCode>)", rf"\g<1>{c}\g<2>"),
                ],
            ),
        ),
        (
            "src/UniversalDownloader.Core/UpdateChecker.cs",
            lambda t: _apply_regex_replacements(
                t,
                [
                    (r'(public string CurrentVersion \{ get; init; \} = ")[^"]+(";)', rf'\g<1>{v}\g<2>'),
                    (r'(public string LatestVersion \{ get; init; \} = ")[^"]+(";)', rf'\g<1>{v}\g<2>'),
                    (r'(public static int AppVersionCode => .*?\? code : )\d+(;)', rf'\g<1>{c}\g<2>'),
                    (r'(if \(ver == null\) return ")[^"]+(";)', rf'\g<1>{v}\g<2>'),
                ],
            ),
        ),
        (
            "src/UniversalDownloader.Avalonia/MainWindow.axaml",
            lambda t: _apply_regex_replacements(
                t,
                [(r'(x:Name="AppVersionBadge"\s+Text="v)[^"]+(")', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            "android/app/build.gradle.kts",
            lambda t: _apply_regex_replacements(
                t,
                [
                    (r'(val cfgVersionName = .*?\?:\s*")[^"]+(")', rf'\g<1>{v}\g<2>'),
                    (r'(val cfgVersionCode = .*?\?:\s*)\d+', rf'\g<1>{c}'),
                ],
            ),
        ),
        (
            "android/README.md",
            lambda t: _apply_regex_replacements(
                t,
                [(r'^(# Universal Media Downloader — Android Edition \(v)[^)]+(\))', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            "browser/extension/manifest.json",
            lambda t: _apply_regex_replacements(
                t,
                [(r'(^\s*"version"\s*:\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
            ),
        ),
        (
            ".github/workflows/release.yml",
            lambda t: _apply_regex_replacements(
                t,
                [
                    (r'(description:\s*"Release Tag \(e\.g\. v)[^)]+(\)")', rf'\g<1>{v}\g<2>'),
                    (r'(default:\s*"v)[^"]+(")', rf'\g<1>{v}\g<2>'),
                ],
            ),
        ),
    ]

    results: list[Tuple[str, bool]] = []
    for rel_path, transform in targets:
        full_path = root / rel_path
        if not full_path.exists():
            continue

        raw_bytes = full_path.read_bytes()
        use_crlf = b"\r\n" in raw_bytes
        original_lf = raw_bytes.decode("utf-8").replace("\r\n", "\n")
        updated_lf = transform(original_lf)

        changed = updated_lf != original_lf
        if changed and not dry_run:
            final_text = updated_lf.replace("\n", "\r\n") if use_crlf else updated_lf
            full_path.write_bytes(final_text.encode("utf-8"))

        results.append((rel_path, changed))

    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update the version number (and version code) across all project files."
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="Target version in MAJOR.MINOR.PATCH format (e.g. 2.3.0 or v2.3.0)",
    )
    bump_group = parser.add_mutually_exclusive_group()
    bump_group.add_argument("--major", action="store_true", help="Bump major version (X+1.0.0)")
    bump_group.add_argument("--minor", action="store_true", help="Bump minor version (X.Y+1.0)")
    bump_group.add_argument("--patch", action="store_true", help="Bump patch version (X.Y.Z+1)")
    bump_group.add_argument("--sync", action="store_true", help="Sync all files to current app_config.json version")
    parser.add_argument("--code", type=int, default=None, help="Explicit integer version_code (Android & Desktop)")
    parser.add_argument("--dry-run", action="store_true", help="Preview files that would change without editing them")
    args = parser.parse_args(argv)

    try:
        current_version, current_code = read_current_version()
        cur_maj, cur_min, cur_pat = parse_semver(current_version)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.sync:
        target_version = current_version
        target_code = args.code if args.code is not None else current_code
    elif args.major:
        target_version = f"{cur_maj + 1}.0.0"
        target_code = args.code if args.code is not None else compute_version_code(cur_maj + 1, 0, 0, current_code)
    elif args.minor:
        target_version = f"{cur_maj}.{cur_min + 1}.0"
        target_code = args.code if args.code is not None else compute_version_code(cur_maj, cur_min + 1, 0, current_code)
    elif args.patch:
        target_version = f"{cur_maj}.{cur_min}.{cur_pat + 1}"
        target_code = args.code if args.code is not None else compute_version_code(cur_maj, cur_min, cur_pat + 1, current_code)
    elif args.version:
        try:
            maj, min_, pat = parse_semver(args.version)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        target_version = f"{maj}.{min_}.{pat}"
        if args.code is not None:
            target_code = args.code
        elif target_version == current_version:
            target_code = current_code
        else:
            target_code = compute_version_code(maj, min_, pat, current_code)
    else:
        print(f"Current version : v{current_version} (version_code: {current_code})")
        raw_input = input("Enter new version (e.g. 2.3.0): ").strip()
        if not raw_input:
            print("Cancelled — no changes made.")
            return 0
        try:
            maj, min_, pat = parse_semver(raw_input)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        target_version = f"{maj}.{min_}.{pat}"
        suggested_code = compute_version_code(maj, min_, pat, current_code)
        raw_code = input(f"Enter version_code [{suggested_code}]: ").strip()
        target_code = int(raw_code) if raw_code.isdigit() else suggested_code

    mode = "DRY RUN" if args.dry_run else "UPDATING"
    print(f"\n[{mode}] v{current_version} ({current_code}) -> v{target_version} ({target_code})\n")

    results = update_all_versions(target_version, target_code, dry_run=args.dry_run)
    changed_count = sum(1 for _, changed in results if changed)

    for rel_path, changed in results:
        tag = "WOULD UPDATE" if (changed and args.dry_run) else ("UPDATED" if changed else "UNCHANGED")
        print(f"  [{tag:<12}] {rel_path}")

    print(f"\nDone: {changed_count}/{len(results)} files {'would be ' if args.dry_run else ''}updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
