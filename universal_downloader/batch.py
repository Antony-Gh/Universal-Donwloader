"""Batch URL ingestion, parallel task execution, and summary reporting."""

from __future__ import annotations

import concurrent.futures
import logging
import random
import threading
import time
from pathlib import Path

from universal_downloader.console import failure, success, warning
from universal_downloader.engine import DownloadEngine
from universal_downloader.exceptions import DownloaderError
from universal_downloader.models import AppConfig, BatchSummary, DownloadResult

LOGGER = logging.getLogger("universal_downloader")


def read_batch_file(path: Path) -> list[str]:
    """Parse text file into cleaned list of non-empty URL lines."""
    if not path.exists():
        raise DownloaderError(f"Batch file does not exist: {path}")

    if not path.is_file():
        raise DownloaderError(f"Batch path is not a file: {path}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DownloaderError(f"Could not read batch file: {path}") from exc

    urls: list[str] = []
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)

    return urls


def run_batch(
    engine: DownloadEngine,
    urls: list[str],
) -> BatchSummary:
    """Execute batch downloads with optional concurrency and polite delays."""
    summary = BatchSummary()
    total = len(urls)
    config = engine.config

    if config.concurrency <= 1:
        # Serial processing
        for index, url in enumerate(urls, start=1):
            if not config.json_output:
                print()
                print("=" * 70)
                print(f"[{index}/{total}] {url}")
                print("=" * 70)

            try:
                result = engine.download(url)
                if result.skipped:
                    summary.skipped += 1
                    if not config.json_output:
                        warning("Skipped.", config)
                else:
                    summary.successful += 1
                    if not config.json_output:
                        success("Download completed.", config)
                        for path in result.files:
                            print(f"  → {path}")

            except Exception as exc:
                summary.failed += 1
                summary.failures.append((url, str(exc)))
                if not config.json_output:
                    failure(f"Download failed: {exc}", config)
                LOGGER.exception("Batch item failed: %s", url)

            # Respect sleep interval
            if config.sleep_interval > 0 and index < total:
                delay = config.sleep_interval
                if config.max_sleep_interval and config.max_sleep_interval > delay:
                    delay = random.uniform(delay, config.max_sleep_interval)
                if config.verbose and not config.json_output:
                    print(f"Sleeping {delay:.1f}s before next download...")
                time.sleep(delay)

        return summary

    # Concurrent processing
    lock = threading.Lock()
    completed_count = 0

    def _worker(item_tuple: tuple[int, str]) -> tuple[str, Optional[DownloadResult], Optional[str]]:
        idx, item_url = item_tuple
        try:
            res = engine.download(item_url)
            return (item_url, res, None)
        except Exception as exc:
            return (item_url, None, str(exc))

    if not config.json_output:
        print(f"Executing batch of {total} items with concurrency={config.concurrency}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        future_map = {
            executor.submit(_worker, (idx, u)): u
            for idx, u in enumerate(urls, start=1)
        }

        for future in concurrent.futures.as_completed(future_map):
            item_url, res, err = future.result()
            with lock:
                completed_count += 1
                if err is not None:
                    summary.failed += 1
                    summary.failures.append((item_url, err))
                    if not config.json_output:
                        failure(f"[{completed_count}/{total}] Failed: {item_url} ({err})", config)
                elif res and res.skipped:
                    summary.skipped += 1
                    if not config.json_output:
                        warning(f"[{completed_count}/{total}] Skipped: {item_url}", config)
                else:
                    summary.successful += 1
                    if not config.json_output:
                        success(f"[{completed_count}/{total}] Completed: {item_url}", config)
                        if res:
                            for path in res.files:
                                print(f"  → {path}")

    return summary


def print_batch_summary(
    summary: BatchSummary,
    config: AppConfig,
) -> None:
    if config.json_output:
        return

    print()
    print("Download Summary")
    print("----------------")
    print(f"✓ Successful: {summary.successful}")
    print(f"✗ Failed:     {summary.failed}")
    print(f"⊘ Skipped:    {summary.skipped}")

    if summary.failures:
        print()
        print("Failed:")
        for index, (url, reason) in enumerate(summary.failures, start=1):
            print(f"{index}. {url}")
            print(f"   {reason}")
