"""Terminal progress formatting and streaming JSON event rendering."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Optional

from universal_downloader.models import AppConfig


def human_size(value: Optional[float]) -> str:
    if value is None:
        return "unknown"

    value = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if abs(value) < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} PB"


def human_speed(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return f"{human_size(value)}/s"


def human_eta(seconds: Optional[int]) -> str:
    if seconds is None:
        return "unknown"

    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def emit_json_event(event_type: str, payload: dict[str, Any]) -> None:
    """Print line-delimited JSON event to stdout for external C#/GUI consumers.
    
    Protected against pipe errors (such as Windows Errno 22) and encoding issues.
    """
    data = {"event": event_type, **payload}
    try:
        sys.stdout.write(json.dumps(data, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except (OSError, IOError, BrokenPipeError, UnicodeError):
        pass


class ProgressRenderer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.last_percent = -1
        self.last_emit_time = 0.0
        self.last_render_time = 0.0

    def reset(self) -> None:
        self.last_percent = -1
        self.last_emit_time = 0.0
        self.last_render_time = 0.0

    def clear_line(self) -> None:
        if self.last_percent >= 0:
            try:
                sys.stdout.write("\r" + " " * 100 + "\r")
                sys.stdout.flush()
            except (OSError, IOError, BrokenPipeError, UnicodeError):
                pass
            self.last_percent = -1

    def __call__(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        now = time.monotonic()

        if self.config.json_stream:
            if status == "downloading":
                downloaded = data.get("downloaded_bytes", 0) or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                percent = (downloaded / total * 100) if total else 0.0
                
                # Rate limit streaming events to ~12 updates/sec unless finished or 100%
                if (now - self.last_emit_time >= 0.08) or (percent >= 100.0):
                    self.last_emit_time = now
                    emit_json_event(
                        "progress",
                        {
                            "status": "downloading",
                            "downloaded_bytes": downloaded,
                            "total_bytes": total,
                            "percent": round(percent, 2),
                            "speed": data.get("speed"),
                            "eta": data.get("eta"),
                            "filename": data.get("filename"),
                        },
                    )
            elif status == "finished":
                self.last_emit_time = 0.0
                emit_json_event(
                    "stage",
                    {"stage": "converting", "message": "Converting, remuxing container and embedding tags..."},
                )
                emit_json_event("postprocess", {"status": "processing"})
            return

        if self.config.json_output:
            return

        if status == "downloading":
            downloaded = data.get("downloaded_bytes", 0) or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")

            if total:
                percent = downloaded / total * 100
                if (now - self.last_render_time >= 0.08) or (percent >= 100.0):
                    self.last_render_time = now
                    bar_width = 30
                    filled = int(bar_width * percent / 100)
                    bar = "█" * filled + "░" * (bar_width - filled)

                    try:
                        sys.stdout.write(
                            f"\r{bar} {percent:6.2f}% "
                            f"| {human_size(downloaded)}/{human_size(total)} "
                            f"| {human_speed(data.get('speed'))} "
                            f"| ETA {human_eta(data.get('eta'))}"
                        )
                        sys.stdout.flush()
                    except (OSError, IOError, BrokenPipeError, UnicodeError):
                        pass
                    self.last_percent = int(percent)

        elif status == "finished":
            self.clear_line()
            if self.config.verbose:
                try:
                    sys.stdout.write("Processing downloaded file...\n")
                    sys.stdout.flush()
                except (OSError, IOError, BrokenPipeError, UnicodeError):
                    pass
