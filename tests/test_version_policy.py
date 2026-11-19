"""Unit tests for remote version deprecation and lifecycle enforcement."""

import json
from unittest.mock import MagicMock, patch

import pytest
from universal_downloader.version_policy import (
    DEFAULT_FALLBACK_POLICY,
    enforce_version_policy,
    evaluate_version_support,
    fetch_remote_version_policy,
    parse_version_tuple,
    render_sunset_banner,
)


def test_parse_version_tuple():
    """Verify semantic version string parsing into comparable integer tuples."""
    assert parse_version_tuple("3.6.0") == (3, 6, 0)
    assert parse_version_tuple("v3.6.0") == (3, 6, 0)
    assert parse_version_tuple("v3.4.1-beta") == (3, 4, 1)
    assert parse_version_tuple("v3.5.0+build100") == (3, 5, 0)
    assert parse_version_tuple("4.0") == (4, 0, 0)
    assert parse_version_tuple("1") == (1, 0, 0)
    assert parse_version_tuple("invalid") == (0, 0, 0)


def test_evaluate_version_support_deprecated():
    """Verify that versions prior to min_supported_version (v3.6.0) are deprecated."""
    policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.7.0",
        "blocked_versions": [],
        "sunset_message": "Version obsolete.",
    }

    allowed, code, msg = evaluate_version_support("3.5.9", policy)
    assert allowed is False
    assert code == "deprecated"
    assert "End of Life" in msg

    allowed, code, msg = evaluate_version_support("3.4.0", policy)
    assert allowed is False
    assert code == "deprecated"

    allowed, code, msg = evaluate_version_support("v2.1.0", policy)
    assert allowed is False
    assert code == "deprecated"


def test_evaluate_version_support_allowed_and_update():
    """Verify current and newer versions are permitted."""
    policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.7.0",
        "blocked_versions": [],
    }

    # v3.6.0 satisfies min, update available to 3.7.0
    allowed, code, msg = evaluate_version_support("3.6.0", policy)
    assert allowed is True
    assert code == "update_available"
    assert "v3.7.0 is available" in msg

    # v3.7.0 satisfies min and equals latest
    allowed, code, msg = evaluate_version_support("3.7.0", policy)
    assert allowed is True
    assert code == "allowed"

    # v3.8.0 is ahead (e.g. dev build)
    allowed, code, msg = evaluate_version_support("3.8.0", policy)
    assert allowed is True
    assert code == "allowed"


def test_evaluate_version_support_blocked_version():
    """Verify explicitly blacklisted versions are blocked."""
    policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.7.0",
        "blocked_versions": ["3.6.2", "v3.6.5"],
    }

    allowed, code, msg = evaluate_version_support("3.6.2", policy)
    assert allowed is False
    assert code == "blocked"
    assert "explicitly revoked or blocked" in msg

    allowed, code, msg = evaluate_version_support("v3.6.5", policy)
    assert allowed is False
    assert code == "blocked"


def test_render_sunset_banner():
    """Verify sunset banner formatting and URLs."""
    policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.7.0",
        "download_url": "https://example.com/download",
        "sunset_message": "Please upgrade immediately.",
    }

    banner = render_sunset_banner("3.5.0", policy)
    assert "VERSION DEPRECATION / END OF LIFE" in banner
    assert "v3.5.0" in banner
    assert "v3.6.0" in banner
    assert "https://example.com/download" in banner
    assert "Please upgrade immediately." in banner


def test_enforce_version_policy_blocking():
    """Verify deprecation enforcement halts when mode is block and allows with force flag."""
    test_policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.6.0",
        "enforcement_mode": "block",
        "sunset_message": "Upgrade required.",
        "download_url": "https://github.com/releases",
    }

    with patch("universal_downloader.version_policy.fetch_remote_version_policy", return_value=test_policy):
        # Deprecated version without force
        allowed, banner = enforce_version_policy(current_version="3.5.0", allow_force=False)
        assert allowed is False
        assert "VERSION DEPRECATION / END OF LIFE" in banner

        # Deprecated version with force bypass
        allowed, msg = enforce_version_policy(current_version="3.5.0", allow_force=True)
        assert allowed is True
        assert "bypassed via --force-deprecated" in msg

        # Supported version
        allowed, msg = enforce_version_policy(current_version="3.6.0", allow_force=False)
        assert allowed is True


def test_enforce_version_policy_warning_mode():
    """Verify deprecation enforcement warns but allows when mode is warn."""
    test_policy = {
        "min_supported_version": "3.6.0",
        "latest_version": "3.6.0",
        "enforcement_mode": "warn",
        "sunset_message": "Warning: Soon to be deprecated.",
    }

    with patch("universal_downloader.version_policy.fetch_remote_version_policy", return_value=test_policy):
        allowed, banner = enforce_version_policy(current_version="3.5.0", allow_force=False)
        assert allowed is True
        assert "VERSION DEPRECATION / END OF LIFE" in banner


def test_fetch_remote_version_policy_fallback_on_network_error():
    """Verify fetch_remote_version_policy gracefully falls back to DEFAULT_FALLBACK_POLICY."""
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        policy = fetch_remote_version_policy(neon_url=None, raw_github_url="https://invalid.example/policy.json")
        assert policy["min_supported_version"] == DEFAULT_FALLBACK_POLICY["min_supported_version"]
        assert policy["enforcement_mode"] == DEFAULT_FALLBACK_POLICY["enforcement_mode"]
