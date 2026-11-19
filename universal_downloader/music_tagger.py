"""Music metadata tagging and cover art enrichment via MusicBrainz & Cover Art Archive."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from universal_downloader.exceptions import DependencyError, DownloadError
from universal_downloader.ffmpeg_manager import ensure_ffmpeg, find_ffmpeg
from universal_downloader.utils.fs import unique_path

LOGGER = logging.getLogger("universal_downloader.music_tagger")

MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/recording/"
COVER_ART_ARCHIVE_URL = "https://coverartarchive.org/release/"
USER_AGENT = "UniversalMediaDownloader/3.6.0 ( https://github.com/Antony-Gh/Universal-Donwloader )"


def clean_track_query(raw_title: str) -> str:
    """Clean video titles (e.g. 'Artist - Song (Official Music Video) [HD]') for MusicBrainz search."""
    cleaned = raw_title
    # Remove bracketed/parenthesized noise like (Official Video), [HQ], (Lyrics), (Official Lyrics)
    cleaned = re.sub(
        r"(?i)\s*[\(\[](?:official\s*(?:music\s*)?(?:video|audio|lyrics)?|video|audio|lyrics|official|hq|hd|4k|remastered|visualizer|ft\..*?|feat\..*?)[\)\]]",
        "",
        cleaned,
    )
    # Remove trailing/leading punctuation
    cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", cleaned)
    return cleaned.strip()


def query_musicbrainz(
    query: str,
    artist: Optional[str] = None,
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Query MusicBrainz recording API for metadata matching query and optional artist.
    Returns dictionary with title, artist, album, date, release_id, track_number.
    """
    clean_q = clean_track_query(query)
    if not clean_q:
        return None

    lucene_query = clean_q
    if artist:
        lucene_query = f'recording:"{clean_q}" AND artist:"{artist}"'

    params = {
        "query": lucene_query,
        "fmt": "json",
        "limit": "3",
    }
    url = f"{MUSICBRAINZ_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        LOGGER.warning("MusicBrainz API request failed: %s", exc)
        return None

    recordings = data.get("recordings", [])
    if not recordings:
        return None

    best = recordings[0]
    rec_title = best.get("title", clean_q)

    # Extract artist credit
    artists_list = best.get("artist-credit", [])
    artist_name = ""
    if artists_list and isinstance(artists_list, list):
        artist_name = "".join(a.get("name", "") + a.get("joinphrase", "") for a in artists_list if isinstance(a, dict))
    artist_name = artist_name.strip() or (artist or "Unknown Artist")

    album_name = ""
    release_date = ""
    release_id = ""

    releases = best.get("releases", [])
    if releases and isinstance(releases, list):
        primary_rel = releases[0]
        album_name = primary_rel.get("title", "")
        release_date = primary_rel.get("date", "")
        release_id = primary_rel.get("id", "")

    return {
        "title": rec_title,
        "artist": artist_name,
        "album": album_name or rec_title,
        "date": release_date[:4] if release_date else "",
        "release_id": release_id,
        "score": best.get("score", 0),
    }


def download_cover_art(release_id: str, dest_path: Path, timeout: int = 10) -> Optional[Path]:
    """Download front cover art for a MusicBrainz release ID."""
    if not release_id:
        return None

    cover_url = f"{COVER_ART_ARCHIVE_URL}{release_id}/front-500"
    req = urllib.request.Request(cover_url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if data:
                dest_path.write_bytes(data)
                return dest_path
    except Exception as exc:
        LOGGER.debug("Cover art not found or download failed for release %s: %s", release_id, exc)
    return None


def build_tag_cmd(
    ffmpeg_bin: Path,
    input_path: Path,
    output_path: Path,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[str] = None,
    cover_image: Optional[Path] = None,
) -> list[str]:
    """Build FFmpeg command to write ID3/Vorbis metadata and optional attached cover art."""
    cmd: list[str] = [
        str(ffmpeg_bin),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
    ]

    has_cover = cover_image and cover_image.exists()
    if has_cover:
        cmd.extend(["-i", str(cover_image)])
        cmd.extend(["-map", "0:a", "-map", "1:0"])
        cmd.extend(["-c", "copy"])
        ext = input_path.suffix.lower()
        if ext == ".mp3":
            cmd.extend(["-id3v2_version", "3", "-metadata:s:v", 'title="Album cover"', "-metadata:s:v", 'comment="Cover (front)"'])
        elif ext in {".m4a", ".mp4"}:
            cmd.extend(["-disposition:v", "attached_pic"])
    else:
        cmd.extend(["-c", "copy"])

    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])
    if album:
        cmd.extend(["-metadata", f"album={album}"])
    if year:
        cmd.extend(["-metadata", f"date={year}"])

    cmd.append(str(output_path))
    return cmd


def tag_audio_file(
    audio_path: Path,
    output_path: Optional[Path] = None,
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[str] = None,
    cover_image: Optional[Path] = None,
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    """Tag audio file with metadata and optional embedded cover art."""
    src = Path(audio_path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Audio file not found: {src}")

    ffmpeg_bin = ffmpeg_path or find_ffmpeg() or ensure_ffmpeg(auto_download=False)
    if not ffmpeg_bin:
        raise DependencyError("FFmpeg is required for audio tagging but was not found.")

    dest = output_path or unique_path(src.parent / f"{src.stem}_tagged{src.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_tag_cmd(
        ffmpeg_bin,
        src,
        dest,
        title=title,
        artist=artist,
        album=album,
        year=year,
        cover_image=cover_image,
    )
    LOGGER.debug("Running FFmpeg audio tagging command: %s", cmd)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DownloadError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"FFmpeg exited with code {proc.returncode}"
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise DownloadError(f"Audio tagging failed: {err}")

    # If no custom output_path was given, replace the original file with the tagged file
    if output_path is None:
        try:
            temp_path = dest
            src.unlink()
            temp_path.replace(src)
            return src.resolve()
        except OSError:
            return dest.resolve()

    return dest.resolve()


def auto_tag_music(
    audio_path: Path,
    title_hint: Optional[str] = None,
    artist_hint: Optional[str] = None,
    ffmpeg_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Search MusicBrainz for the audio file, download cover art, and tag the file.
    Returns metadata dict if tagged successfully, None otherwise.
    """
    query = title_hint or audio_path.stem
    meta = query_musicbrainz(query, artist=artist_hint)
    if not meta:
        return None

    cover_file = None
    if meta.get("release_id"):
        cover_temp = audio_path.parent / f"{audio_path.stem}_cover.jpg"
        cover_file = download_cover_art(meta["release_id"], cover_temp)

    tag_audio_file(
        audio_path,
        title=meta.get("title"),
        artist=meta.get("artist"),
        album=meta.get("album"),
        year=meta.get("date"),
        cover_image=cover_file,
        ffmpeg_path=ffmpeg_path,
    )

    if cover_file and cover_file.exists():
        try:
            cover_file.unlink()
        except OSError:
            pass

    return meta
