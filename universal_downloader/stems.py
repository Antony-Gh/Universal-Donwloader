"""AI Vocal & Instrumental Stems Separation / Karaoke Extractor.

Separates mixed audio tracks into isolated vocals and instrumental/karaoke accompaniment
using Demucs deep learning when available, with a fast, zero-dependency FFmpeg center-channel
phase-cancellation fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
from typing import Optional

from universal_downloader.ffmpeg_manager import find_ffmpeg

LOGGER = logging.getLogger("universal_downloader.stems")


def separate_stems(
    input_file: Path | str,
    output_dir: Optional[Path | str] = None,
    *,
    mode: str = "both",  # "both", "karaoke" (instrumental), "vocals"
) -> dict[str, Path]:
    """Separate audio into instrumental and vocal tracks.

    Returns dict mapping stem name ("instrumental", "vocals") to output file Path.
    """
    source = Path(input_file).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source media file not found: {source}")

    out_folder = Path(output_dir).resolve() if output_dir else source.parent
    out_folder.mkdir(parents=True, exist_ok=True)

    stem_name = source.stem
    results: dict[str, Path] = {}

    # 1. Try Demucs AI if available
    demucs_bin = shutil.which("demucs")
    if demucs_bin:
        try:
            LOGGER.info("Demucs AI found. Running neural stem separation on: %s", source.name)
            cmd = [
                demucs_bin,
                "--two-stems=vocals",
                "-o",
                str(out_folder),
                str(source),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                # Look for generated stems in out_folder / htdemucs / stem_name / ...
                demucs_out_dir = out_folder / "htdemucs" / stem_name
                if not demucs_out_dir.exists():
                    # check first subfolder
                    cand = list(out_folder.glob(f"*/{stem_name}"))
                    if cand:
                        demucs_out_dir = cand[0]

                voc = demucs_out_dir / "vocals.wav"
                inst = demucs_out_dir / "no_vocals.wav"

                if mode in ("both", "vocals") and voc.is_file():
                    target_voc = out_folder / f"{stem_name}_vocals.wav"
                    shutil.move(str(voc), str(target_voc))
                    results["vocals"] = target_voc

                if mode in ("both", "karaoke") and inst.is_file():
                    target_inst = out_folder / f"{stem_name}_instrumental.wav"
                    shutil.move(str(inst), str(target_inst))
                    results["instrumental"] = target_inst

                if results:
                    return results
        except Exception as demucs_exc:
            LOGGER.warning("Demucs execution failed, falling back to FFmpeg: %s", demucs_exc)

    # 2. FFmpeg Phase Cancellation / Bandpass Center Extraction
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        raise RuntimeError("FFmpeg is required for vocal/instrumental separation.")

    # Instrumental / Karaoke Stem (attenuates center vocal channel)
    if mode in ("both", "karaoke"):
        inst_path = out_folder / f"{stem_name}_instrumental.mp3"
        # Center-channel vocal reduction via out-of-phase cross cancellation and voice EQ notch
        inst_filter = "pan=stereo|c0=c0-0.85*c1|c1=c1-0.85*c0,equalizer=f=350:t=q:w=1:g=-4"
        cmd = [
            str(ffmpeg_bin),
            "-y",
            "-i",
            str(source),
            "-af",
            inst_filter,
            "-b:a",
            "320k",
            str(inst_path),
        ]
        LOGGER.info("Generating instrumental karaoke track: %s", inst_path.name)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0 and inst_path.is_file():
            results["instrumental"] = inst_path
        else:
            LOGGER.warning("FFmpeg karaoke extraction failed: %s", proc.stderr)

    # Isolated Vocals Stem (isolates center vocal frequencies)
    if mode in ("both", "vocals"):
        voc_path = out_folder / f"{stem_name}_vocals.mp3"
        voc_filter = "pan=mono|c0=0.5*c0+0.5*c1,highpass=f=220,lowpass=f=3800"
        cmd = [
            str(ffmpeg_bin),
            "-y",
            "-i",
            str(source),
            "-af",
            voc_filter,
            "-b:a",
            "320k",
            str(voc_path),
        ]
        LOGGER.info("Extracting isolated vocals stem: %s", voc_path.name)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0 and voc_path.is_file():
            results["vocals"] = voc_path
        else:
            LOGGER.warning("FFmpeg vocals isolation failed: %s", proc.stderr)

    return results
