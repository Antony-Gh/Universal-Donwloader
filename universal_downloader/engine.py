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
        # Fast inspection for TikTok without cookies to avoid Cloudflare/Akamai bot detection & timeouts
        if (platform == Platform.TIKTOK or "tiktok.com" in url.lower()) and not getattr(self.config, "cookies_file", None) and not getattr(self.config, "cookies_from_browser", None):
            fb = self._fallback_tiktok_inspect(url)
            if fb:
                return fb

        extra_opts: dict[str, Any] = {
            "skip_download": True,
            "ignoreerrors": True,
            **self.extractor.platform_extra_options(platform),
        }
        if flat_playlist:
            extra_opts["extract_flat"] = "in_playlist"
        if playlist_items:
            extra_opts["playlist_items"] = playlist_items
        try:
            return self.extractor.extract_info(
                url,
                download=False,
                extra=extra_opts,
            )
        except Exception:
            if platform == Platform.TIKTOK or "tiktok.com" in url.lower():
                fb = self._fallback_tiktok_inspect(url)
                if fb:
                    return fb
            raise

    @staticmethod
    def _fallback_tiktok_inspect(url: str) -> Optional[dict[str, Any]]:
        clean_url = url.split("?")[0].strip()
        import ssl
        ssl_ctx = None
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            try:
                ssl_ctx = ssl._create_unverified_context()
            except Exception:
                ssl_ctx = None

        # 1. TikWM lookup (faster & provides direct play links)
        try:
            import urllib.request
            import urllib.parse
            import json as _json
            import html as _html
            api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(clean_url)}"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            try:
                r = urllib.request.urlopen(req, timeout=5, context=ssl_ctx)
            except Exception:
                r = urllib.request.urlopen(req, timeout=5, context=ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None)
            with r:
                res = _json.loads(r.read().decode("utf-8"))
                d = res.get("data")
                if res.get("code") == 0 and isinstance(d, dict):
                    author = (d.get("author") or {}).get("nickname") or "TikTok Creator"
                    raw_title = d.get("title") or f"TikTok Video by {author}"
                    desc = _html.unescape(raw_title)
                    cover = d.get("cover")
                    dl_url = d.get("play")
                    duration = d.get("duration")
                    formats = [
                        {
                            "format_id": "best",
                            "ext": "mp4",
                            "resolution": "1080p",
                            "vcodec": "h264",
                            "acodec": "aac",
                            "format_note": "Best (HD No Watermark)",
                            "url": dl_url,
                        }
                    ] if dl_url else []
                    return {
                        "id": str(d.get("id") or ""),
                        "title": desc,
                        "uploader": author,
                        "channel": author,
                        "creator": author,
                        "description": desc,
                        "thumbnail": cover,
                        "duration": duration,
                        "duration_string": f"{duration}s" if duration else None,
                        "view_count": d.get("play_count"),
                        "like_count": d.get("digg_count"),
                        "formats": formats,
                        "webpage_url": clean_url,
                        "extractor": "tiktok",
                        "extractor_key": "TikTok",
                        "_fallback_download_url": dl_url,
                    }
        except Exception as e:
            LOGGER.debug("TikWM fallback inspect failed: %s", e)

        # 2. TikMate lookup
        try:
            import urllib.request
            import urllib.parse
            import json as _json
            import html as _html
            data = urllib.parse.urlencode({"url": clean_url}).encode()
            req = urllib.request.Request(
                "https://api.tikmate.app/api/lookup",
                data=data,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            try:
                r = urllib.request.urlopen(req, timeout=6, context=ssl_ctx)
            except Exception:
                r = urllib.request.urlopen(req, timeout=6, context=ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None)
            with r:
                res = _json.loads(r.read().decode("utf-8"))
                if res.get("success"):
                    author = res.get("author_name") or res.get("author_id") or "TikTok Creator"
                    raw_title = res.get("desc") or f"TikTok Video by {author}"
                    desc = _html.unescape(raw_title)
                    cover = res.get("cover") or res.get("dynamic_cover")
                    token = res.get("token")
                    vid_id = str(res.get("id") or "")
                    dl_url = f"https://tikmate.app/download/{token}/{vid_id}.mp4" if token and vid_id else None
                    formats = [
                        {
                            "format_id": "best",
                            "ext": "mp4",
                            "resolution": "1080p",
                            "vcodec": "h264",
                            "acodec": "aac",
                            "format_note": "Best (HD No Watermark)",
                            "url": dl_url,
                        }
                    ] if dl_url else []
                    return {
                        "id": vid_id,
                        "title": desc,
                        "uploader": author,
                        "channel": author,
                        "creator": author,
                        "description": desc,
                        "thumbnail": cover,
                        "duration": None,
                        "duration_string": None,
                        "view_count": res.get("like_count"),
                        "like_count": res.get("like_count"),
                        "comment_count": res.get("comment_count"),
                        "formats": formats,
                        "webpage_url": clean_url,
                        "extractor": "tiktok",
                        "extractor_key": "TikTok",
                        "_fallback_download_url": dl_url,
                    }
        except Exception as e:
            LOGGER.debug("TikMate fallback inspect failed: %s", e)

        return None

    @staticmethod
    def _fallback_facebook_inspect(url: str) -> Optional[dict[str, Any]]:
        clean_url = url.split("?")[0].strip()
        import ssl
        ssl_ctx = None
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            try:
                ssl_ctx = ssl._create_unverified_context()
            except Exception:
                ssl_ctx = None

        try:
            import urllib.request
            import re
            import html as _html
            req = urllib.request.Request(
                clean_url,
                headers={
                    "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            try:
                r = urllib.request.urlopen(req, timeout=6, context=ssl_ctx)
            except Exception:
                r = urllib.request.urlopen(req, timeout=6, context=ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None)
            with r:
                raw = r.read().decode("utf-8", errors="ignore")
                title_m = re.search(r'property="og:title"\s+content="([^"]+)"', raw)
                desc_m = re.search(r'property="og:description"\s+content="([^"]+)"', raw)
                img_m = re.search(r'property="og:image"\s+content="([^"]+)"', raw)
                if title_m or img_m:
                    title = _html.unescape(title_m.group(1)) if title_m else ""
                    # Ignore Facebook login/error walls
                    lowered_title = title.lower()
                    if lowered_title.startswith("log in") or lowered_title.startswith("sign up") or lowered_title.startswith("login"):
                        title = ""

                    desc = _html.unescape(desc_m.group(1)) if desc_m else ""
                    cover = _html.unescape(img_m.group(1)) if img_m else None
                    if not title and not cover:
                        return None

                    author = "Facebook Creator"
                    if "|" in title:
                        parts = title.split("|")
                        last_p = parts[-1].strip()
                        if last_p and len(last_p) < 60:
                            author = last_p
                    return {
                        "id": clean_url.rstrip("/").split("/")[-1],
                        "title": title or f"Facebook Video by {author}",
                        "uploader": author,
                        "channel": author,
                        "creator": author,
                        "description": desc,
                        "thumbnail": cover,
                        "duration": None,
                        "duration_string": None,
                        "view_count": None,
                        "formats": [
                            {
                                "format_id": "best",
                                "ext": "mp4",
                                "resolution": "1080p",
                                "vcodec": "h264",
                                "acodec": "aac",
                                "format_note": "Best (HD)",
                            }
                        ],
                        "webpage_url": clean_url,
                        "extractor": "facebook",
                        "extractor_key": "Facebook",
                    }
        except Exception as e:
            LOGGER.debug("Facebook OpenGraph fallback inspect failed: %s", e)
        return None

        return None

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

        if target.platform == Platform.TIKTOK:
            # If no cookies provided, use fast direct fallback first to avoid Cloudflare/Akamai bot blocking
            if not getattr(self.config, "cookies_file", None) and not getattr(self.config, "cookies_from_browser", None):
                fb_info = self._fallback_tiktok_inspect(target.normalized_url)
                if fb_info and fb_info.get("_fallback_download_url"):
                    LOGGER.info("Downloading TikTok video directly via HD stream...")
                    return self._download_direct_fallback(target, fb_info, output_template, progress)

            try:
                progress.reset()
                return self.extractor.download(
                    target.normalized_url,
                    output_template,
                    selector,
                    progress,
                    platform=target.platform,
                    attempt=attempt,
                    is_playlist=(target.content_type == ContentType.PLAYLIST),
                )
            except Exception as exc:
                LOGGER.info("Primary TikTok extraction failed (%s); downloading via direct HD stream...", exc)
                fb_info = self._fallback_tiktok_inspect(target.normalized_url)
                if fb_info and fb_info.get("_fallback_download_url"):
                    LOGGER.info("Falling back to direct stream download for TikTok video.")
                    return self._download_direct_fallback(target, fb_info, output_template, progress)
                raise

    def _download_direct_fallback(
        self,
        target: DetectedTarget,
        info_data: dict[str, Any],
        output_template: str,
        progress: ProgressRenderer,
    ) -> dict[str, Any]:
        import urllib.request
        import re
        dl_url = info_data["_fallback_download_url"]
        clean_title = re.sub(r'[\\/*?:"<>|]', "_", info_data.get("title") or "tiktok_video")[:60].strip() or "tiktok_video"
        out_dir = self.config.output_dir / platform_directory(target.platform)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest_file = out_dir / f"{clean_title}.mp4"

        req = urllib.request.Request(
            dl_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://tikmate.app/",
                "Accept": "*/*",
                "Connection": "keep-alive",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest_file, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress({
                            "status": "downloading",
                            "downloaded_bytes": downloaded,
                            "total_bytes": total_size,
                            "filename": str(dest_file),
                        })

        progress.clear_line()

        # Handle audio extraction if requested
        if self.config.audio_only:
            audio_dest = dest_file.with_suffix(".mp3")
            ffmpeg_bin = find_ffmpeg() or ensure_ffmpeg(auto_download=True)
            if ffmpeg_bin:
                import subprocess
                cmd = [
                    str(ffmpeg_bin),
                    "-y",
                    "-i", str(dest_file),
                    "-vn",
                    "-acodec", "libmp3lame",
                    "-q:a", "2",
                    str(audio_dest),
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if audio_dest.is_file() and audio_dest.stat().st_size > 0:
                    try:
                        dest_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                    dest_file = audio_dest

        res = dict(info_data)
        res["_filename"] = str(dest_file.resolve())
        res["requested_downloads"] = [{"filepath": str(dest_file.resolve())}]
        return res

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

        if self.config.rules_enabled:
            from universal_downloader.rules import RulesEngine
            try:
                engine_rules = RulesEngine(rules_path=self.config.rules_file)
                applied = engine_rules.apply(
                    config=self.config,
                    platform=target.platform.value,
                )
                if applied:
                    LOGGER.info("Applied platform smart rules: %s", applied)
            except Exception as rexc:
                LOGGER.warning("Initial rules evaluation error: %s", rexc)

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

                # Post-metadata rules evaluation (keywords, duration, uploader)
                if self.config.rules_enabled and res.metadata:
                    from universal_downloader.rules import RulesEngine
                    try:
                        engine_rules = RulesEngine(rules_path=self.config.rules_file)
                        post_applied = engine_rules.apply(
                            config=self.config,
                            platform=target.platform.value,
                            title=res.metadata.get("title", ""),
                            uploader=res.metadata.get("uploader", ""),
                            duration=res.metadata.get("duration"),
                        )
                        if post_applied:
                            LOGGER.info("Applied post-metadata smart rules: %s", post_applied)
                    except Exception as prexc:
                        LOGGER.warning("Post-metadata rules evaluation error: %s", prexc)

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

                # Automatic Vocal & Instrumental Stem Separation / Karaoke
                if self.config.karaoke or self.config.isolate_vocals:
                    from universal_downloader.stems import separate_stems
                    stem_mode = "both" if (self.config.karaoke and self.config.isolate_vocals) else ("karaoke" if self.config.karaoke else "vocals")
                    for f in list(res.files):
                        if f.suffix.lower() in {".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".opus", ".mp4", ".mkv", ".webm"}:
                            try:
                                if self.config.json_stream:
                                    emit_json_event(
                                        "stage",
                                        {"stage": "stems", "message": f"Separating stems for {f.name}..."},
                                    )
                                stem_files = separate_stems(f, output_dir=f.parent, mode=stem_mode)
                                for sf in stem_files.values():
                                    if sf not in res.files:
                                        res.files.append(sf)
                            except Exception as stem_exc:
                                LOGGER.warning("Stems separation failed: %s", stem_exc)

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

                # Automatic NAS / Cloud Backup
                if self.config.backup_target and res.files:
                    from universal_downloader.backup import backup_media_file
                    for f in res.files:
                        try:
                            if self.config.json_stream:
                                emit_json_event(
                                    "stage",
                                    {"stage": "backup", "message": f"Backing up {f.name} to {self.config.backup_target}..."},
                                )
                            ok = backup_media_file(
                                f,
                                self.config.backup_target,
                                username=self.config.backup_user,
                                password=self.config.backup_pass,
                            )
                            if ok and not self.config.json_output and not self.config.json_stream:
                                success(f"Backed up {f.name} -> {self.config.backup_target}", self.config)
                        except Exception as b_exc:
                            LOGGER.warning("Automatic backup failed for %s: %s", f.name, b_exc)

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
