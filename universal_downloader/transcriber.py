"""Local AI transcription and summarization using Whisper and faster-whisper."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LOGGER = logging.getLogger("universal_downloader.transcriber")

# Stopwords for lightweight extractive summarization
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
}


def format_timestamp(seconds: float, decimal_sep: str = ",") -> str:
    """Format seconds into HH:MM:SS,mmm or HH:MM:SS.mmm format."""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d}{decimal_sep}{millis:03d}"


def write_srt(segments: List[Dict[str, Any]], output_path: Path) -> Path:
    """Write subtitle segments to SubRip (.srt) file."""
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        start = format_timestamp(seg.get("start", 0.0), ",")
        end = format_timestamp(seg.get("end", 0.0), ",")
        text = str(seg.get("text", "")).strip()
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_vtt(segments: List[Dict[str, Any]], output_path: Path) -> Path:
    """Write subtitle segments to WebVTT (.vtt) file."""
    lines: List[str] = ["WEBVTT\n"]
    for idx, seg in enumerate(segments, 1):
        start = format_timestamp(seg.get("start", 0.0), ".")
        end = format_timestamp(seg.get("end", 0.0), ".")
        text = str(seg.get("text", "")).strip()
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_txt(segments: List[Dict[str, Any]], output_path: Path) -> Path:
    """Write transcript segments to plain text (.txt) file."""
    full_text = " ".join(str(seg.get("text", "")).strip() for seg in segments if seg.get("text"))
    # Normalize excessive spaces
    full_text = re.sub(r"\s+", " ", full_text).strip()
    output_path.write_text(full_text + "\n", encoding="utf-8")
    return output_path


def summarize_text(text: str, max_sentences: int = 5) -> str:
    """
    Lightweight, fast extractive summarizer.
    Scores sentences based on word frequency distribution (excluding stopwords)
    and preserves original chronological flow.
    """
    if not text.strip():
        return ""

    # Split into sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) <= max_sentences:
        return "\n".join(f"• {s}" for s in sentences)

    # Word frequencies
    words = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", text.lower())
    freqs: Dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freqs[w] = freqs.get(w, 0) + 1

    if not freqs:
        return "\n".join(f"• {s}" for s in sentences[:max_sentences])

    max_freq = max(freqs.values())

    # Score each sentence
    scored_sentences: List[Tuple[float, int, str]] = []
    for idx, sentence in enumerate(sentences):
        sent_words = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", sentence.lower())
        if not sent_words:
            continue
        score = sum(freqs.get(w, 0) / max_freq for w in sent_words) / math.sqrt(len(sent_words))
        scored_sentences.append((score, idx, sentence))

    # Pick top N sentences by score
    scored_sentences.sort(key=lambda x: x[0], reverse=True)
    top_picks = scored_sentences[:max_sentences]

    # Reorder chronologically
    top_picks.sort(key=lambda x: x[1])
    return "\n".join(f"• {item[2]}" for item in top_picks)


def transcribe_media(
    media_path: Path,
    output_dir: Optional[Path] = None,
    model_name: str = "base",
    language: Optional[str] = None,
    formats: Tuple[str, ...] = ("srt", "txt", "vtt"),
    summarize: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Path]:
    """
    Transcribe a video or audio file using Whisper or faster-whisper.
    Generates .srt, .vtt, .txt, and optionally .summary.txt.
    """
    if not media_path.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    out_folder = output_dir or media_path.parent
    out_folder.mkdir(parents=True, exist_ok=True)
    stem = media_path.stem

    if progress_callback:
        progress_callback(f"Loading Whisper model '{model_name}'...")

    segments: List[Dict[str, Any]] = []

    # 1. Try faster-whisper
    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_name, device="auto", compute_type="auto")
        kwargs: Dict[str, Any] = {}
        if language and language.lower() not in {"auto", "none"}:
            kwargs["language"] = language

        seg_gen, _info = model.transcribe(str(media_path), **kwargs)
        for s in seg_gen:
            segments.append({
                "start": s.start,
                "end": s.end,
                "text": s.text,
            })
    except ImportError:
        # 2. Try openai-whisper
        try:
            import whisper  # type: ignore

            model = whisper.load_model(model_name)
            kwargs = {}
            if language and language.lower() not in {"auto", "none"}:
                kwargs["language"] = language
            result = model.transcribe(str(media_path), **kwargs)
            for s in result.get("segments", []):
                segments.append({
                    "start": s.get("start", 0.0),
                    "end": s.get("end", 0.0),
                    "text": s.get("text", ""),
                })
        except ImportError:
            raise RuntimeError(
                "Whisper is not installed. To use offline AI transcription, run:\n"
                "  pip install faster-whisper\n"
                "or\n"
                "  pip install openai-whisper"
            )

    output_files: Dict[str, Path] = {}
    normalized_formats = {f.lower().lstrip(".") for f in formats}

    if "srt" in normalized_formats:
        srt_path = out_folder / f"{stem}.srt"
        write_srt(segments, srt_path)
        output_files["srt"] = srt_path

    if "vtt" in normalized_formats:
        vtt_path = out_folder / f"{stem}.vtt"
        write_vtt(segments, vtt_path)
        output_files["vtt"] = vtt_path

    if "txt" in normalized_formats or summarize:
        txt_path = out_folder / f"{stem}.txt"
        write_txt(segments, txt_path)
        output_files["txt"] = txt_path

    if summarize:
        full_text = " ".join(s.get("text", "").strip() for s in segments)
        summary = summarize_text(full_text)
        summary_path = out_folder / f"{stem}.summary.txt"
        summary_path.write_text(summary + "\n", encoding="utf-8")
        output_files["summary"] = summary_path

    return output_files
