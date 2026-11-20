"""Bilingual & Dual Subtitle Generator and Merger for Universal Media Downloader.

Allows parsing, aligning, and merging two subtitle tracks (e.g. English + Arabic,
or English + Spanish) into a synchronized bilingual dual-subtitle file (.srt).
Useful for language learners, international cinema, and multi-lingual households.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

LOGGER = logging.getLogger("universal_downloader")


@dataclass
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    start_str: str
    end_str: str
    text: str


def parse_timestamp_to_ms(ts: str) -> int:
    """Convert SRT/VTT timestamp string (00:01:23,456 or 00:01:23.456) to milliseconds."""
    clean = ts.strip().replace(".", ",")
    parts = clean.split(":")
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].split(",")
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        return (h * 3600 + m * 60 + s) * 1000 + ms
    elif len(parts) == 2:
        m = int(parts[0])
        s_parts = parts[1].split(",")
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        return (m * 60 + s) * 1000 + ms
    return 0


def format_ms_to_srt(ms: int) -> str:
    """Format millisecond integer into standard SRT timestamp HH:MM:SS,mmm."""
    ms = max(0, ms)
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(content: str) -> List[SubtitleCue]:
    """Parse SRT string content into a list of SubtitleCue objects."""
    blocks = re.split(r"\n\s*\n", content.strip())
    cues: List[SubtitleCue] = []
    cue_idx = 1

    time_pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{2}:\d{2}[,\.]\d{1,3})"
    )

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        match = None
        text_start_idx = 1
        for idx, line in enumerate(lines[:3]):
            m = time_pattern.search(line)
            if m:
                match = m
                text_start_idx = idx + 1
                break

        if not match:
            continue

        start_str = match.group(1).replace(".", ",")
        end_str = match.group(2).replace(".", ",")
        start_ms = parse_timestamp_to_ms(start_str)
        end_ms = parse_timestamp_to_ms(end_str)

        text = "\n".join(lines[text_start_idx:]).strip()
        if not text:
            continue

        cues.append(
            SubtitleCue(
                index=cue_idx,
                start_ms=start_ms,
                end_ms=end_ms,
                start_str=format_ms_to_srt(start_ms),
                end_str=format_ms_to_srt(end_ms),
                text=text,
            )
        )
        cue_idx += 1

    return cues


def format_srt(cues: List[SubtitleCue]) -> str:
    """Serialize a list of SubtitleCue objects into standard SRT formatted string."""
    output_blocks = []
    for idx, cue in enumerate(cues, start=1):
        output_blocks.append(
            f"{idx}\n{cue.start_str} --> {cue.end_str}\n{cue.text}\n"
        )
    return "\n".join(output_blocks).strip() + "\n"


def merge_dual_subtitles(
    primary_cues: Union[List[SubtitleCue], Path, str],
    secondary_cues: Union[List[SubtitleCue], Path, str],
    output_path: Optional[Path] = None,
    *,
    layout: str = "stacked",
    primary_color: Optional[str] = None,
    secondary_color: Optional[str] = "#38BDF8",
) -> List[SubtitleCue]:
    """Merge two subtitle tracks into synchronized bilingual dual subtitles.

    Matches cues from both tracks based on maximum temporal overlap.
    """
    # Load primary cues
    if isinstance(primary_cues, (str, Path)) and Path(primary_cues).is_file():
        p_cues = parse_srt(Path(primary_cues).read_text(encoding="utf-8", errors="ignore"))
    elif isinstance(primary_cues, str):
        p_cues = parse_srt(primary_cues)
    else:
        p_cues = list(primary_cues)

    # Load secondary cues
    if isinstance(secondary_cues, (str, Path)) and Path(secondary_cues).is_file():
        s_cues = parse_srt(Path(secondary_cues).read_text(encoding="utf-8", errors="ignore"))
    elif isinstance(secondary_cues, str):
        s_cues = parse_srt(secondary_cues)
    else:
        s_cues = list(secondary_cues)

    if not p_cues:
        return s_cues
    if not s_cues:
        return p_cues

    merged: List[SubtitleCue] = []

    for p in p_cues:
        # Find best matching secondary cue with time overlap
        best_match: Optional[SubtitleCue] = None
        best_overlap = 0

        for s in s_cues:
            overlap = min(p.end_ms, s.end_ms) - max(p.start_ms, s.start_ms)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = s

        p_text = p.text
        if primary_color:
            p_text = f"<font color=\"{primary_color}\">{p_text}</font>"

        if best_match and best_overlap > 200:
            s_text = best_match.text
            if secondary_color:
                s_text = f"<font color=\"{secondary_color}\">{s_text}</font>"

            if layout == "side_by_side":
                combined_text = f"{p_text}  |  {s_text}"
            else:  # stacked
                combined_text = f"{p_text}\n{s_text}"
        else:
            combined_text = p_text

        merged.append(
            SubtitleCue(
                index=len(merged) + 1,
                start_ms=p.start_ms,
                end_ms=p.end_ms,
                start_str=p.start_str,
                end_str=p.end_str,
                text=combined_text,
            )
        )

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(format_srt(merged), encoding="utf-8")
        LOGGER.info(f"Wrote merged dual-subtitles to: {output_path}")

    return merged
