"""Application exception definitions."""

from __future__ import annotations


class DownloaderError(Exception):
    """Base application exception."""


class ConfigurationError(DownloaderError):
    """Invalid configuration."""


class DependencyError(DownloaderError):
    """Required dependency is missing."""


class UnsupportedPlatformError(DownloaderError):
    """The requested URL/platform is not supported."""


class ExtractionError(DownloaderError):
    """Media extraction failed."""


class DownloadError(DownloaderError):
    """Media download failed."""


class ProfileError(DownloaderError):
    """Profile resolution failed."""
