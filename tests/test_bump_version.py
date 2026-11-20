"""Tests for scripts/bump_version.py version updater."""

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
import pytest


def _load_bump_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_parse_semver_and_compute_code():
    mod = _load_bump_module()
    assert mod.parse_semver("2.3.1") == (2, 3, 1)
    assert mod.parse_semver("v3.0.0") == (3, 0, 0)
    with pytest.raises(ValueError):
        mod.parse_semver("2.3")

    assert mod.compute_version_code(2, 3, 0, current_code=150) == 230
    assert mod.compute_version_code(2, 2, 1, current_code=250) == 251


def test_update_all_versions_in_isolated_copy():
    mod = _load_bump_module()
    repo_root = Path(__file__).resolve().parent.parent
    rel_files = [
        "app_config.json",
        "pyproject.toml",
        "universal_downloader/__init__.py",
        "build_and_publish.py",
        "installer/windows/build_msi.py",
        "src/Directory.Build.props",
        "src/UniversalDownloader.Core/UpdateChecker.cs",
        "src/UniversalDownloader.Avalonia/MainWindow.axaml",
        "android/app/build.gradle.kts",
        "android/README.md",
        "browser/extension/manifest.json",
        ".github/workflows/release.yml",
    ]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for rel in rel_files:
            src = repo_root / rel
            dst = tmp_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        results = mod.update_all_versions("9.8.7", 987, root=tmp_root, dry_run=False)
        assert len(results) == len(rel_files)
        assert all(changed for _, changed in results)

        cfg = json.loads((tmp_root / "app_config.json").read_text(encoding="utf-8"))
        assert cfg["version_name"] == "9.8.7"
        assert cfg["version_code"] == 987

        for rel in rel_files:
            content = (tmp_root / rel).read_text(encoding="utf-8")
            assert "9.8.7" in content, f"Missing new version in {rel}"

        # Running a second time with same version should be a complete no-op
        second = mod.update_all_versions("9.8.7", 987, root=tmp_root, dry_run=False)
        assert all(not changed for _, changed in second)
