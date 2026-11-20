from pathlib import Path
import pytest
from universal_downloader.subtitles import (
    SubtitleCue,
    format_ms_to_srt,
    format_srt,
    merge_dual_subtitles,
    parse_srt,
    parse_timestamp_to_ms,
)


SAMPLE_EN_SRT = """1
00:00:01,000 --> 00:00:04,000
Welcome to Universal Media Downloader.

2
00:00:05,000 --> 00:00:08,500
Enjoy your videos and music with zero ads.
"""

SAMPLE_AR_SRT = """1
00:00:01,200 --> 00:00:03,800
مرحباً بكم في يونيفرسال ميديا داونلودر.

2
00:00:05,100 --> 00:00:08,400
استمتع بالفيديوهات والموسيقى بدون إعلانات.
"""


def test_timestamp_parsing_and_formatting():
    ms = parse_timestamp_to_ms("01:23:45,678")
    assert ms == (1 * 3600 + 23 * 60 + 45) * 1000 + 678
    formatted = format_ms_to_srt(ms)
    assert formatted == "01:23:45,678"


def test_parse_and_format_srt():
    cues = parse_srt(SAMPLE_EN_SRT)
    assert len(cues) == 2
    assert cues[0].index == 1
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 4000
    assert "Universal Media" in cues[0].text

    serialized = format_srt(cues)
    assert "00:00:01,000 --> 00:00:04,000" in serialized
    assert "Welcome to Universal Media" in serialized


def test_merge_dual_subtitles(tmp_path: Path):
    en_file = tmp_path / "en.srt"
    ar_file = tmp_path / "ar.srt"
    out_file = tmp_path / "dual.srt"

    en_file.write_text(SAMPLE_EN_SRT, encoding="utf-8")
    ar_file.write_text(SAMPLE_AR_SRT, encoding="utf-8")

    merged = merge_dual_subtitles(en_file, ar_file, output_path=out_file)
    assert len(merged) == 2
    assert "Welcome to Universal Media Downloader." in merged[0].text
    assert "مرحباً بكم في يونيفرسال ميديا داونلودر." in merged[0].text
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "1" in content
    assert "00:00:01,000 --> 00:00:04,000" in content
    assert "استمتع بالفيديوهات" in content
