"""Download engine orchestration, output template selection, retries, and lifecycle management."""

from __future__ import annotations

import logging
from pathlib import Path
import random
import tempfile
import time
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
from universal_downloader.integrity import (
    compute_sha256,
    verify_media_integrity,
    write_sha256_sidecar,
)
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
from universal_downloader.paths import get_default_download_dir
from universal_downloader.profile import (
    ProfilePhotoResolver,
    extract_username_from_profile_url,
    resolve_profile_input,
)
from universal_downloader.progress import ProgressRenderer, emit_json_event
from universal_downloader.utils.fs import (
    ensure_inside_directory,
    platform_directory,
    rename_with_clean_title,
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
        organize = (getattr(self.config, "organize", "platform") or "platform").strip().lower()

        def _base_for(root: Path) -> Path:
            if organize == "none":
                return root
            return root / platform_directory(target.platform)

        try:
            base = _base_for(self.config.output_dir)
            base.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            LOGGER.warning(
                "Configured output directory '%s' is not writable; falling back to Downloads folder",
                self.config.output_dir,
            )
            self.config.output_dir = get_default_download_dir()
            try:
                base = _base_for(self.config.output_dir)
                base.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError):
                temp_dir = Path(tempfile.gettempdir()) / "UniversalDownloader" / "downloads"
                temp_dir.mkdir(parents=True, exist_ok=True)
                self.config.output_dir = temp_dir
                base = _base_for(temp_dir)
                base.mkdir(parents=True, exist_ok=True)

        if organize == "uploader":
            routed_base = base / "%(uploader,channel,uploader_id|Unknown)s"
        elif organize == "date":
            routed_base = base / "%(upload_date>%Y-%m|Undated)s"
        else:
            routed_base = base

        if self.config.output_template:
            # If the template is already an absolute path, respect it; otherwise nest in routed_base
            tmpl = self.config.output_template
            if not tmpl.startswith(("/", "\\")) and ":" not in tmpl[:2]:
                return str(routed_base / tmpl)
            return tmpl

        if target.content_type == ContentType.PLAYLIST:
            return str(routed_base / "%(playlist_title)s" / "%(playlist_index)02d - %(title).150B [%(id)s].%(ext)s")

        if self.config.audio_only:
            if organize == "uploader":
                return str(routed_base / "%(title).150B.%(ext)s")
            return str(routed_base / "%(uploader)s - %(title).150B.%(ext)s")

        if organize == "uploader":
            return str(routed_base / "%(title).150B [%(id)s].%(ext)s")
        return str(routed_base / "%(uploader)s - %(title).150B [%(id)s].%(ext)s")

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

        if target.content_type == ContentType.PROFILE:
            if target.platform in {
                Platform.FACEBOOK,
                Platform.INSTAGRAM,
                Platform.TWITTER,
                Platform.THREADS,
            }:
                saved_profile = self.download_profile(target.normalized_url)
                return DownloadResult(
                    success=True,
                    url=target.normalized_url,
                    files=[saved_profile],
                    metadata={"title": saved_profile.stem, "platform": target.platform.value},
                )
            if not self.config.json_output:
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

            if getattr(self.config, "clean_filenames", False):
                path = rename_with_clean_title(path, info_dict.get("title"))
                ensure_inside_directory(self.config.output_dir, path)

            if getattr(self.config, "verify_integrity", False):
                ok_integrity, reason = verify_media_integrity(path)
                if not ok_integrity:
                    raise DownloadError(f"Media integrity check failed for '{path.name}': {reason}")

            if getattr(self.config, "write_checksum", False):
                digest = compute_sha256(path)
                write_sha256_sidecar(path, digest=digest)
                info_dict["sha256"] = digest
                downloaded_info["sha256"] = digest

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
        if self.config.json_stream:
            emit_json_event(
                "stage",
                {"stage": "extracting", "message": "Extracting media streams and stream metadata..."},
            )

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
        if self.config.json_stream:
            emit_json_event(
                "stage",
                {"stage": "preparing", "message": "Initializing download engine and target validation..."},
            )

        target = detect_target(url, timeout=self.config.timeout)

        LOGGER.info(
            "Target detected platform=%s type=%s url=%s",
            target.platform.value,
            target.content_type.value,
            target.normalized_url,
        )

        if self.config.json_stream:
            emit_json_event(
                "stage",
                {
                    "stage": "checking",
                    "message": f"Target verified ({target.platform.value}). Resolving streams...",
                    "platform": target.platform.value,
                },
            )

        if self.config.check_duplicates:
            from universal_downloader.duplicate_detector import find_existing_duplicate
            dup = find_existing_duplicate(target.normalized_url, self.config.output_dir)
            if dup:
                dup_path = dup["path"]
                LOGGER.info("Duplicate download detected: %s", dup_path)
                if self.config.json_stream:
                    emit_json_event(
                        "duplicate",
                        {
                            "url": target.normalized_url,
                            "existing_file": str(dup_path),
                            "message": f"Duplicate file already exists: {dup_path.name}",
                        },
                    )
                if not self.config.json_output:
                    warning(f"Duplicate detected! You already downloaded this file:\n  • {dup_path}", self.config)
                return DownloadResult(
                    success=True,
                    url=target.normalized_url,
                    files=[dup_path],
                    metadata={"title": dup.get("title") or dup_path.stem, "duplicate": True},
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

                # Automatic Whisper transcription
                if self.config.transcribe:
                    try:
                        from universal_downloader.transcriber import transcribe_media
                        formats_tuple = tuple(fmt.strip() for fmt in self.config.transcribe_format.split(",") if fmt.strip())
                        for f in list(res.files):
                            if f.suffix.lower() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}:
                                if self.config.json_stream:
                                    emit_json_event(
                                        "stage",
                                        {"stage": "transcribing", "message": f"Transcribing {f.name} with Whisper..."},
                                    )
                                out_files = transcribe_media(
                                    f,
                                    output_dir=f.parent,
                                    model_name=self.config.whisper_model,
                                    language=self.config.whisper_lang,
                                    formats=formats_tuple,
                                    summarize=self.config.summarize,
                                )
                                for tf in out_files.values():
                                    if tf not in res.files:
                                        res.files.append(tf)
                    except Exception as texc:
                        LOGGER.warning("Automatic transcription skipped or failed: %s", texc)
                        if self.config.verbose:
                            warning(f"Transcription failed: {texc}", self.config)

                # Automatic GIF conversion & Frame Grab
                if self.config.to_gif or self.config.frame_grab:
                    from universal_downloader.converter import extract_frame, video_to_gif
                    for f in list(res.files):
                        if f.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}:
                            if self.config.to_gif:
                                try:
                                    gif_path = video_to_gif(
                                        f,
                                        start_time=self.config.start_time,
                                        duration=self.config.record_duration,
                                        fps=self.config.gif_fps,
                                        width=self.config.gif_width,
                                    )
                                    if gif_path not in res.files:
                                        res.files.append(gif_path)
                                except Exception as gexc:
                                    LOGGER.warning("GIF generation failed: %s", gexc)
                            if self.config.frame_grab:
                                try:
                                    frame_path = extract_frame(
                                        f,
                                        timestamp=str(self.config.frame_grab),
                                    )
                                    if frame_path not in res.files:
                                        res.files.append(frame_path)
                                except Exception as fexc:
                                    LOGGER.warning("Frame grab failed: %s", fexc)

                # Automatic MusicBrainz music tagging
                if self.config.tag_music:
                    from universal_downloader.music_tagger import auto_tag_music
                    for f in list(res.files):
                        if f.suffix.lower() in {".mp3", ".m4a", ".flac", ".opus", ".wav", ".aac"}:
                            try:
                                if self.config.json_stream:
                                    emit_json_event(
                                        "stage",
                                        {"stage": "tagging", "message": f"Tagging {f.name} with MusicBrainz..."},
                                    )
                                auto_tag_music(
                                    f,
                                    title_hint=res.metadata.get("title"),
                                    artist_hint=res.metadata.get("uploader"),
                                )
                            except Exception as m_exc:
                                LOGGER.warning("Music tagging skipped or failed: %s", m_exc)

                # Desktop notification
                if self.config.notify:
                    title_str = res.metadata.get("title") or "Download Complete"
                    send_notification("Universal Downloader", f"Downloaded: {title_str}")

                # Local network file share
                if self.config.share and res.files:
                    try:
                        from universal_downloader.local_share import generate_qr_ascii, start_file_share
                        primary_file = res.files[0]
                        server = start_file_share(primary_file, port=self.config.share_port)
                        qr_ascii = generate_qr_ascii(server.url)
                        if self.config.json_stream:
                            emit_json_event(
                                "share",
                                {
                                    "share_url": server.url,
                                    "file": str(primary_file),
                                },
                            )
                        if not self.config.json_output and not self.config.json_stream:
                            print("\n" + "=" * 60)
                            print(f"📲 Sharing '{primary_file.name}' over Local Wi-Fi")
                            print(f"👉 Scan QR code with your phone camera or visit: {server.url}")
                            print("=" * 60)
                            print(qr_ascii)
                    except Exception as s_exc:
                        LOGGER.warning("Local file sharing failed: %s", s_exc)

                # JSON streaming event
                if self.config.json_stream:
                    emit_json_event(
                        "stage",
                        {"stage": "completed", "message": "Download and conversion finished successfully."},
                    )
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

                is_youtube_403 = (
                    target.platform == Platform.YOUTUBE
                    and ("http error 403" in lowered_err or "403: forbidden" in lowered_err)
                )

                if is_youtube_403 and attempt <= self.config.retries:
                    LOGGER.info(
                        "YouTube returned HTTP 403 on attempt %d; rotating player client and retrying...",
                        attempt,
                    )

                if is_non_retryable_error(message) and not is_youtube_403:
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
