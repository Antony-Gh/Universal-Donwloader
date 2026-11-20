import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from universal_downloader.models import AppConfig
from universal_downloader.rules import RoutingRule, RulesEngine, get_default_rules


def test_routing_rule_matching():
    rule = RoutingRule(
        name="Soundcloud Rule",
        platforms=["soundcloud"],
        keywords=["remix"],
        min_duration=60.0,
        max_duration=300.0,
        actions={"format": "audio", "audio_format": "mp3"}
    )

    # Full match
    assert rule.matches(platform="soundcloud", title="Awesome Song (Remix)", duration=180.0)

    # Platform mismatch
    assert not rule.matches(platform="youtube", title="Awesome Song (Remix)", duration=180.0)

    # Keyword mismatch
    assert not rule.matches(platform="soundcloud", title="Awesome Song (Original)", duration=180.0)

    # Duration too short
    assert not rule.matches(platform="soundcloud", title="Awesome Song (Remix)", duration=30.0)

    # Duration too long
    assert not rule.matches(platform="soundcloud", title="Awesome Song (Remix)", duration=500.0)


def test_rules_engine_apply(tmp_path):
    config = AppConfig(output_dir=tmp_path)
    engine = RulesEngine(rules=get_default_rules(), rules_path=tmp_path / "rules.json")

    # Match Soundcloud music rule
    applied = engine.apply(config, platform="soundcloud", title="Chill Beats", duration=120.0)
    assert "Audio Streaming Platforms Auto-MP3" in applied
    assert config.format == "audio"
    assert config.audio_format == "mp3"
    assert config.output_dir.name == "Music"

    # Match long podcast rule
    config2 = AppConfig(output_dir=tmp_path)
    applied2 = engine.apply(config2, platform="youtube", title="Tech Podcast Episode 42", duration=3600.0)
    assert "Long Podcasts & Lectures (Whisper + Chapters)" in applied2
    assert config2.transcribe is True
    assert config2.split_chapters is True
    assert config2.output_dir.name == "Podcasts"


def test_rules_persistence(tmp_path):
    file_path = tmp_path / "custom_rules.json"
    custom_rules = [
        RoutingRule(
            name="Vimeo 4K Rule",
            platforms=["vimeo"],
            actions={"preset": "tv_theater"}
        )
    ]
    engine = RulesEngine(rules=custom_rules, rules_path=file_path)
    engine.save_rules()

    assert file_path.is_file()

    # Reload from file
    engine2 = RulesEngine(rules=None, rules_path=file_path)
    assert len(engine2.rules) == 1
    assert engine2.rules[0].name == "Vimeo 4K Rule"
    assert engine2.rules[0].actions == {"preset": "tv_theater"}
