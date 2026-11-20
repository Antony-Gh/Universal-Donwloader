"""Smart routing and automation rules engine for Universal Media Downloader.

Evaluates media attributes (platform, title keywords, uploader, duration)
and dynamically routes downloads to specific directories, formats, presets,
and post-processing pipelines (Whisper transcription, chapter splitting, dual subtitles).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

LOGGER = logging.getLogger("universal_downloader.rules")

DEFAULT_RULES_FILE = Path.home() / ".universal_downloader" / "rules.json"


@dataclass
class RoutingRule:
    """Represents a single conditional smart routing rule."""

    name: str
    platforms: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    uploaders: List[str] = field(default_factory=list)
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    actions: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        platform: str = "",
        title: str = "",
        uploader: str = "",
        duration: Optional[float] = None,
    ) -> bool:
        """Evaluate if the current media metadata matches this rule's conditions."""
        plat_norm = (platform or "").strip().lower()
        title_norm = (title or "").strip().lower()
        uploader_norm = (uploader or "").strip().lower()

        # Check platform match
        if self.platforms:
            if not any(p.strip().lower() in plat_norm or plat_norm in p.strip().lower() for p in self.platforms):
                return False

        # Check title keywords
        if self.keywords:
            if not any(k.strip().lower() in title_norm for k in self.keywords):
                return False

        # Check uploader match
        if self.uploaders:
            if not any(u.strip().lower() in uploader_norm for u in self.uploaders):
                return False

        # Check duration
        if self.min_duration is not None:
            if duration is None or duration < self.min_duration:
                return False

        if self.max_duration is not None:
            if duration is None or duration > self.max_duration:
                return False

        return True


def get_default_rules() -> List[RoutingRule]:
    """Provide sensible, production-ready default routing rules."""
    return [
        RoutingRule(
            name="Audio Streaming Platforms Auto-MP3",
            platforms=["soundcloud", "bandcamp", "mixcloud", "spotify", "audiomack"],
            actions={
                "format": "audio",
                "audio_format": "mp3",
                "output_subfolder": "Music",
            },
        ),
        RoutingRule(
            name="Long Podcasts & Lectures (Whisper + Chapters)",
            keywords=["podcast", "interview", "lecture", "tutorial", "keynote"],
            min_duration=1800.0,  # 30+ minutes
            actions={
                "transcribe": True,
                "split_chapters": True,
                "output_subfolder": "Podcasts",
            },
        ),
        RoutingRule(
            name="Mobile & Social Shorts Quick Sharing",
            platforms=["tiktok", "instagram", "reels", "shorts"],
            max_duration=180.0,  # 3 minutes or less
            actions={
                "preset": "whatsapp",
                "output_subfolder": "Shorts",
            },
        ),
    ]


class RulesEngine:
    """Manages loading, persistence, and execution of routing rules."""

    def __init__(self, rules: Optional[List[RoutingRule]] = None, rules_path: Optional[Path] = None):
        self.rules_path = Path(rules_path) if rules_path else DEFAULT_RULES_FILE
        if rules is not None:
            self.rules = rules
        else:
            self.rules = self.load_rules()

    def load_rules(self) -> List[RoutingRule]:
        """Load rules from file or fallback to default rules."""
        if self.rules_path and self.rules_path.is_file():
            try:
                data = json.loads(self.rules_path.read_text(encoding="utf-8"))
                rules = []
                for item in data:
                    rules.append(
                        RoutingRule(
                            name=item.get("name", "Unnamed Rule"),
                            platforms=item.get("platforms", []),
                            keywords=item.get("keywords", []),
                            uploaders=item.get("uploaders", []),
                            min_duration=item.get("min_duration"),
                            max_duration=item.get("max_duration"),
                            actions=item.get("actions", {}),
                        )
                    )
                return rules
            except Exception as exc:
                LOGGER.warning("Failed to load rules from %s: %s", self.rules_path, exc)

        return get_default_rules()

    def save_rules(self, path: Optional[Path] = None) -> None:
        """Persist current rules to JSON file."""
        target = Path(path) if path else self.rules_path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "name": r.name,
                "platforms": r.platforms,
                "keywords": r.keywords,
                "uploaders": r.uploaders,
                "min_duration": r.min_duration,
                "max_duration": r.max_duration,
                "actions": r.actions,
            }
            for r in self.rules
        ]
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def apply(
        self,
        config: Any,
        platform: str = "",
        title: str = "",
        uploader: str = "",
        duration: Optional[float] = None,
    ) -> List[str]:
        """Apply all matching rules to dynamically adjust the configuration."""
        applied_names: List[str] = []

        for rule in self.rules:
            if rule.matches(platform=platform, title=title, uploader=uploader, duration=duration):
                applied_names.append(rule.name)
                LOGGER.info("Applied Smart Routing Rule: '%s'", rule.name)

                # Process actions
                actions = rule.actions
                if "format" in actions:
                    config.format = actions["format"]
                if "audio_format" in actions:
                    config.audio_format = actions["audio_format"]
                if "preset" in actions:
                    config.preset = actions["preset"]
                if "transcribe" in actions:
                    config.transcribe = bool(actions["transcribe"])
                if "split_chapters" in actions:
                    config.split_chapters = bool(actions["split_chapters"])
                if "dual_subs" in actions:
                    config.dual_subs = bool(actions["dual_subs"])
                if "output_subfolder" in actions:
                    subfolder = str(actions["output_subfolder"]).strip()
                    if subfolder and hasattr(config, "output_dir"):
                        current_out = Path(config.output_dir)
                        # Avoid repeatedly appending the same subfolder
                        if current_out.name != subfolder:
                            config.output_dir = current_out / subfolder

        return applied_names
