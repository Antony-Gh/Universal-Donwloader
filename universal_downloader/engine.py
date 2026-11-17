"""Download engine orchestration, output template selection, retries, and lifecycle management."""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any, Optional

from universal_downloader.console import info, warning
from universal_downloader.exceptions import (
    DependencyError,
    DownloadError,
    ExtractionError,
    ProfileError,
    UnsupportedPlatformError,
)
from universal_downloader.extractor import YTDLPExtractor
from universal_downloader.formats import quality_to_selector
from universal_downloader.history import get_db_path, record_download
from universal_downloader.logging_utils import (
    TIKTOK_INTERNAL_RETRIES,
    TIKTOK_RETRY_DELAYS,
    clean_error_message,
    is_non_retryable_error,
    is_tiktok_rehydration_error,
)
from universal_downloader.models import (
    AppConfig,
    ContentType,
    DetectedTarget,
    DownloadResult,
    Platform,
)
from universal_downloader.notify import send_notification
from universal_downloader.profile import (
    ProfilePhotoResolver,
    extract_username_from_profile_url,
    resolve_profile_input,
)
from universal_downloader.progress import ProgressRenderer, emit_json_event
from universal_downloader.utils.fs import (
    ensure_inside_directory,
    platform_directory,
    write_metadata_file,
)
from universal_downloader.utils.net import detect_target

LOGGER = logging.getLogger("universal_downloader")


class DownloadEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.extractor = YTDLPExtractor(config)
        self.profile_resolver = ProfilePhotoResolver(config, self.extractor)

    def choose_output_template(self, target: DetectedTarget) -> str:
        base = self.config.output_dir / platform_directory(target.platform)
        base.mkdir(parents=True, exist_ok=True)

        if self.config.output_template:
            # If the template is already an absolute path, respect it; otherwise nest in base
            tmpl = self.config.output_template
            if not tmpl.startswith(("/", "\\")) and ":" not in tmpl[:2]:
                return str(base / tmpl)
            return tmpl

        if target.content_type == ContentType.PLAYLIST:
            return str(base / "%(playlist_title)s" / "%(playlist_index)02d - %(title).150B [%(id)s].%(ext)s")

        if self.config.audio_only:
            return str(base / "%(uploader)s - %(title).150B.%(ext)s")

        return str(base / "%(uploader)s - %(title).150B [%(id)s].%(ext)s")

    def inspect(
        self,
        url: str,
        platform: Platform = Platform.UNKNOWN,
        flat_playlist: bool = False,
        playlist_items: Optional[str] = None,
    ) -> dict[str, Any]:
        extra_opts: dict[str, Any] = {
            "skip_download": True,
            "ignoreerrors": True,
            **self.extractor.platform_extra_options(platform),
        }
        if flat_playlist:
            extra_opts["extract_flat"] = "in_playlist"
        if playlist_items:
            extra_opts["playlist_items"] = playlist_items
        return self.extractor.extract_info(
            url,
            download=False,
            extra=extra_opts,
        )

    def download_once(self, target: DetectedTarget, attempt: int = 1) -> DownloadResult:
        if target.platform == Platform.WHATSAPP:
            raise UnsupportedPlatformError(
                "WhatsApp is not implemented as a private-client downloader. "
                "No private chat or session circumvention is attempted."
            )

        if target.platform == Platform.UNKNOWN and not self.config.json_output:
            warning("Unknown domain; attempting generic extraction.", self.config)

        if target.content_type == ContentType.PROFILE and not self.config.json_output:
            warning(
                "This appears to be a profile URL. Use --profile for profile-picture mode.",
                self.config,
            )

        # Dry-run mode: extract metadata only and report
        if self.config.dry_run:
            info_data = self.inspect(target.normalized_url, platform=target.platform)
            if not self.config.json_output:
                info(f"[Dry-run] Title: {info_data.get('title') or 'unknown'}", self.config)
                info(f"[Dry-run] Uploader: {info_data.get('uploader') or 'unknown'}", self.config)
                info(f"[Dry-run] Simulated download for {target.normalized_url}", self.config)
            return DownloadResult(
                success=True,
                url=target.normalized_url,
                files=[],
                metadata=info_data,
            )

        output_template = self.choose_output_template(target)
        selector = quality_to_selector(self.config.quality, self.config.audio_only, self.config.prefer_codec)
        progress = ProgressRenderer(self.config)

        downloaded_info = self._download_media(
            target,
            output_template,
            selector,
            progress,
            attempt=attempt,
        )

        files_and_info: list[tuple[Path, dict[str, Any]]] = []

        # Check if downloaded media is a playlist / collection
        is_playlist = (
            downloaded_info.get("_type") in ("playlist", "multi_video")
            or "entries" in downloaded_info
        )

        if is_playlist:
            raw_entries = downloaded_info.get("entries") or []
            entries = [e for e in raw_entries if isinstance(e, dict)]
            for entry in entries:
                entry_files: list[str] = []
                reqs = entry.get("requested_downloads")
                if isinstance(reqs, list):
                    for req in reqs:
                        if isinstance(req, dict) and req.get("filepath"):
                            entry_files.append(req["filepath"])
                if entry.get("_filename"):
                    entry_files.append(entry["_filename"])

                for fpath in entry_files:
                    path_obj = Path(fpath)
                    if path_obj.exists():
                        files_and_info.append((path_obj.resolve(), entry))

        else:
            # Single item extraction
            single_paths: list[str] = []
            requested = downloaded_info.get("requested_downloads")
            if isinstance(requested, list):
                for item in requested:
                    if isinstance(item, dict) and item.get("filepath"):
                        single_paths.append(item["filepath"])

            if downloaded_info.get("_filename"):
                single_paths.append(downloaded_info["_filename"])

            for fpath in single_paths:
                path_obj = Path(fpath)
                if path_obj.exists():
                    files_and_info.append((path_obj.resolve(), downloaded_info))

        # Fallback to inspecting output directory if yt-dlp did not report filenames
        if not files_and_info:
            output_dir = self.config.output_dir / platform_directory(target.platform)
            if output_dir.exists():
                candidates = sorted(
                    (
                        path
                        for path in output_dir.rglob("*")
                        if path.is_file()
                        and not path.name.endswith(".json")
                        and not path.name.endswith(".part")
                        and not path.name.endswith(".ytdl")
                    ),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    files_and_info.append((candidates[0].resolve(), downloaded_info))

        if not files_and_info:
            raise DownloadError(
                "yt-dlp reported success but output files could not be located on disk."
            )

        unique_files: list[Path] = []
        seen: set[str] = set()

        for path, info_dict in files_and_info:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)

            # Security boundary verification
            ensure_inside_directory(self.config.output_dir, path)
            unique_files.append(path)

            if self.config.write_metadata:
                write_metadata_file(path, info_dict, target.normalized_url)

        return DownloadResult(
            success=True,
            url=target.normalized_url,
            files=unique_files,
            metadata=downloaded_info,
        )

    def _download_media(
        self,
        target: DetectedTarget,
        output_template: str,
        selector: str,
        progress: ProgressRenderer,
        attempt: int = 1,
    ) -> dict[str, Any]:
        if target.platform != Platform.TIKTOK:
            return self.extractor.download(
                target.normalized_url,
                output_template,
                selector,
                progress,
                platform=target.platform,
                attempt=attempt,
                is_playlist=(target.content_type == ContentType.PLAYLIST),
            )

        last_error: Optional[DownloadError] = None

        for attempt in range(TIKTOK_INTERNAL_RETRIES):
            try:
                progress.reset()
                return self.extractor.download(
                    target.normalized_url,
                    output_template,
                    selector,
                    progress,
                    platform=target.platform,
                )
            except DownloadError as exc:
                last_error = exc
                if not is_tiktok_rehydration_error(str(exc)):
                    raise

                if attempt >= TIKTOK_INTERNAL_RETRIES - 1:
                    break

                delay = TIKTOK_RETRY_DELAYS[
                    min(attempt, len(TIKTOK_RETRY_DELAYS) - 1)
                ] + random.uniform(0.25, 1.25)

                progress.clear_line()
                LOGGER.info(
                    "TikTok access blocked (attempt %d/%d); retrying in %ds",
                    attempt + 1,
                    TIKTOK_INTERNAL_RETRIES,
                    delay,
                )
                time.sleep(delay)

        if last_error:
            raise last_error

        raise DownloadError("TikTok download failed after internal retries.")

    def download(self, url: str) -> DownloadResult:
        target = detect_target(url, timeout=self.config.timeout)

        LOGGER.info(
            "Target detected platform=%s type=%s url=%s",
            target.platform.value,
            target.content_type.value,
            target.normalized_url,
        )

        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.retries + 2):
            try:
                res = self.download_once(target, attempt=attempt)

                # History tracking
                if not self.config.no_history:
                    record_download(
                        get_db_path(self.config.output_dir),
                        target.normalized_url,
                        res.files,
                        res.metadata,
                        status="completed",
                    )

                # Desktop notification
                if self.config.notify:
                    title_str = res.metadata.get("title") or "Download Complete"
                    send_notification("Universal Downloader", f"Downloaded: {title_str}")

                # JSON streaming event
                if self.config.json_stream:
                    emit_json_event(
                        "complete",
                        {
                            "url": target.normalized_url,
                            "files": [str(p) for p in res.files],
                            "title": res.metadata.get("title"),
                            "uploader": res.metadata.get("uploader"),
                        },
                    )

                return res

            except (
                DownloadError,
                ExtractionError,
                DependencyError,
            ) as exc:
                last_error = exc
                message = clean_error_message(str(exc))
                lowered_err = message.lower()

                if (
                    "certificate verify failed" in lowered_err
                    or "certificateverifyerror" in lowered_err
                    or "unable to get local issuer certificate" in lowered_err
                ):
                    LOGGER.info(
                        "SSL certificate verification issue encountered. Retrying with certificate verification disabled..."
                    )
                    self.config.no_check_certificate = True
                    self.extractor.config.no_check_certificate = True

                if is_non_retryable_error(message):
                    break

                if (
                    target.platform == Platform.TIKTOK
                    and is_tiktok_rehydration_error(message)
                ):
                    break

                if attempt > self.config.retries:
                    break

                delay = min(2 ** (attempt - 1), 15)

                if self.config.verbose:
                    warning(
                        f"Transient failure. Retry "
                        f"{attempt}/{self.config.retries} in {delay}s...",
                        self.config,
                    )

                LOGGER.warning(
                    "Download attempt %d failed: %s",
                    attempt,
                    exc,
                )
                time.sleep(delay)

            except UnsupportedPlatformError:
                raise

            except Exception as exc:
                LOGGER.exception("Unexpected download failure.")
                last_error = exc
                break

        if last_error:
            if not self.config.no_history:
                record_download(
                    get_db_path(self.config.output_dir),
                    target.normalized_url,
                    [],
                    {},
                    status="failed",
                    error=str(last_error),
                )

            if self.config.notify:
                send_notification("Universal Downloader", f"Failed: {last_error}")

            if self.config.json_stream:
                emit_json_event(
                    "error",
                    {"url": target.normalized_url, "error": str(last_error)},
                )

            raise last_error

        raise DownloadError("Download failed for an unknown reason.")

    def download_profile(self, profile_value: str) -> Path:
        profile_url = resolve_profile_input(profile_value)
        target = detect_target(profile_url, timeout=self.config.timeout)

        if target.platform in {Platform.UNKNOWN, Platform.WHATSAPP}:
            raise ProfileError("The supplied profile cannot be resolved safely.")

        username = extract_username_from_profile_url(
            target.normalized_url,
            target.platform,
        )

        return self.profile_resolver.resolve(
            target.normalized_url,
            target.platform,
            username,
        )
