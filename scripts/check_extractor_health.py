"""Automated extractor health check script for daily CI monitoring.

Probes major platforms (YouTube, TikTok, Twitter/X, Instagram, Reddit, Vimeo, SoundCloud)
using non-destructive format inspection and produces a GitHub Actions Step Summary table.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from universal_downloader.engine import DownloadEngine
from universal_downloader.models import AppConfig, Platform

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("extractor_health")

# Standard canonical public test URLs
CANONICAL_HEALTH_TARGETS = [
    {
        "platform": "YouTube (Standard Video)",
        "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # "Me at the zoo" (First YouTube video)
    },
    {
        "platform": "YouTube (Shorts)",
        "url": "https://www.youtube.com/shorts/3iP_37l8pYg",
    },
    {
        "platform": "Vimeo",
        "url": "https://vimeo.com/76979871",
    },
    {
        "platform": "SoundCloud",
        "url": "https://soundcloud.com/forss/flickermood",
    },
    {
        "platform": "Reddit",
        "url": "https://www.reddit.com/r/aww/comments/92xqnf/pure_joy/",
    },
]


@dataclass
class HealthCheckResult:
    platform: str
    url: str
    success: bool
    latency_sec: float
    title: Optional[str] = None
    stream_count: int = 0
    error_message: Optional[str] = None


def run_health_check(
    engine: DownloadEngine,
    platform_name: str,
    url: str,
    timeout: int = 25,
) -> HealthCheckResult:
    """Probe a single platform's extractor health by inspecting stream availability."""
    start_t = time.time()
    try:
        LOGGER.info("Checking %s: %s", platform_name, url)
        info = engine.inspect(url)
        elapsed = time.time() - start_t
        title = info.get("title") or "Unknown Title"
        formats = info.get("formats") or []
        return HealthCheckResult(
            platform=platform_name,
            url=url,
            success=True,
            latency_sec=round(elapsed, 2),
            title=title,
            stream_count=len(formats),
        )
    except Exception as exc:
        elapsed = time.time() - start_t
        LOGGER.warning("Health check failed for %s: %s", platform_name, exc)
        return HealthCheckResult(
            platform=platform_name,
            url=url,
            success=False,
            latency_sec=round(elapsed, 2),
            error_message=str(exc)[:120],
        )


def generate_markdown_report(results: List[HealthCheckResult]) -> str:
    """Generate a GitHub Flavored Markdown summary report table."""
    total = len(results)
    passed = sum(1 for r in results if r.success)
    failed = total - passed
    overall_badge = "🟢 ALL OPERATIONAL" if failed == 0 else f"🔴 {failed} EXTRACTOR(S) FAILING"

    lines = [
        f"## 🩺 Extractor Health Status: {overall_badge}",
        f"",
        f"**Health Summary:** {passed}/{total} platforms operational ({round(passed / total * 100 if total else 0)}%).",
        f"Last checked at: `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`",
        f"",
        f"| Platform | Status | Response Time | Streams Found | Details |",
        f"| :--- | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        status_icon = "✅ Operational" if r.success else "❌ Failing"
        latency = f"{r.latency_sec}s"
        streams = str(r.stream_count) if r.success else "0"
        detail = f"_{r.title}_" if r.success else f"`{r.error_message}`"
        lines.append(f"| **{r.platform}** | {status_icon} | {latency} | {streams} | {detail} |")

    lines.append("")
    lines.append("> _Automated daily synthetic monitoring via Universal Media Downloader CI._")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily extractor health checks.")
    parser.add_argument("--output-markdown", type=Path, help="Path to save markdown health report.")
    parser.add_argument("--json", action="store_true", help="Print results as JSON.")
    args = parser.parse_args()

    config = AppConfig(timeout=30, retries=1)
    engine = DownloadEngine(config)

    results: List[HealthCheckResult] = []
    for item in CANONICAL_HEALTH_TARGETS:
        res = run_health_check(engine, item["platform"], item["url"])
        results.append(res)

    md_report = generate_markdown_report(results)

    # Write to GitHub Step Summary if running in GitHub Actions
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        try:
            with open(gh_summary, "a", encoding="utf-8") as f:
                f.write("\n\n" + md_report + "\n")
            LOGGER.info("Wrote health report to GITHUB_STEP_SUMMARY")
        except Exception as exc:
            LOGGER.warning("Could not write to GITHUB_STEP_SUMMARY: %s", exc)

    if args.output_markdown:
        args.output_markdown.write_text(md_report, encoding="utf-8")
        LOGGER.info("Saved markdown report to %s", args.output_markdown)

    if args.json:
        data = [
            {
                "platform": r.platform,
                "url": r.url,
                "success": r.success,
                "latency_sec": r.latency_sec,
                "stream_count": r.stream_count,
                "error": r.error_message,
            }
            for r in results
        ]
        print(json.dumps(data, indent=2))
    else:
        print("\n" + md_report)

    # Exit with code 1 if any extractor failed
    has_failures = any(not r.success for r in results)
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
