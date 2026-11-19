import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from universal_downloader.music_tagger import (
    clean_track_query,
    build_tag_cmd,
    query_musicbrainz,
    tag_audio_file,
    auto_tag_music,
)


def test_clean_track_query():
    assert clean_track_query("Adele - Rolling in the Deep (Official Music Video)") == "Adele - Rolling in the Deep"
    assert clean_track_query("Queen - Bohemian Rhapsody [HD] (Official Lyrics)") == "Queen - Bohemian Rhapsody"
    assert clean_track_query("Coldplay - Yellow (Audio)") == "Coldplay - Yellow"


def test_build_tag_cmd(tmp_path: Path):
    ffmpeg = Path("ffmpeg")
    src = tmp_path / "song.mp3"
    out = tmp_path / "song_tagged.mp3"
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"image")

    cmd = build_tag_cmd(
        ffmpeg,
        src,
        out,
        title="Song Title",
        artist="Artist Name",
        album="Album Name",
        year="2024",
        cover_image=cover,
    )

    cmd_str = " ".join(cmd)
    assert "-metadata title=Song Title" in cmd_str
    assert "-metadata artist=Artist Name" in cmd_str
    assert "-metadata album=Album Name" in cmd_str
    assert "-metadata date=2024" in cmd_str
    assert "-id3v2_version 3" in cmd_str
    assert "attached_pic" in cmd_str or "Album cover" in cmd_str


@patch("urllib.request.urlopen")
def test_query_musicbrainz(mock_urlopen):
    fake_response = {
        "recordings": [
            {
                "title": "Imagine",
                "artist-credit": [{"name": "John Lennon", "joinphrase": ""}],
                "releases": [
                    {"id": "rel-12345", "title": "Imagine", "date": "1971-09-09"}
                ],
                "score": 100,
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    meta = query_musicbrainz("John Lennon - Imagine")
    assert meta is not None
    assert meta["title"] == "Imagine"
    assert meta["artist"] == "John Lennon"
    assert meta["album"] == "Imagine"
    assert meta["date"] == "1971"
    assert meta["release_id"] == "rel-12345"


@patch("universal_downloader.music_tagger.subprocess.run")
def test_tag_audio_file(mock_run, tmp_path: Path):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"dummy mp3 data")

    def _fake_run(cmd, **_kwargs):
        dest = Path(cmd[-1])
        dest.write_bytes(b"tagged mp3 data")
        res = MagicMock()
        res.returncode = 0
        return res

    mock_run.side_effect = _fake_run
    tagged = tag_audio_file(
        src,
        title="Title",
        artist="Artist",
        ffmpeg_path=Path("ffmpeg"),
    )
    assert tagged.exists()
    assert tagged.name == "track.mp3"
