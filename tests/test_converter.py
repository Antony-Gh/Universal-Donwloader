"""Tests for universal_downloader.converter (direct local FFmpeg media converter)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from universal_downloader.cli import main
from universal_downloader.converter import build_ffmpeg_convert_cmd, convert_media_file
from universal_downloader.exceptions import DependencyError, DownloadError


def test_build_ffmpeg_convert_cmd_audio_and_video(tmp_path: Path) -> None:
    ffmpeg = Path("/usr/bin/ffmpeg")
    src = tmp_path / "lecture.mp4"
    out_mp3 = tmp_path / "lecture.mp3"
    out_mp4 = tmp_path / "lecture.remux.mp4"
    out_webm = tmp_path / "lecture.webm"

    cmd_mp3 = build_ffmpeg_convert_cmd(ffmpeg, src, out_mp3, "mp3", audio_quality="320k")
    assert "-vn" in cmd_mp3
    assert "libmp3lame" in cmd_mp3
    assert "320k" in cmd_mp3
    assert "-map_metadata" in cmd_mp3

    cmd_remux = build_ffmpeg_convert_cmd(ffmpeg, src, out_mp4, "mp4", remux_only=True)
    assert "-c" in cmd_remux and "copy" in cmd_remux
    assert "+faststart" in cmd_remux

    cmd_webm = build_ffmpeg_convert_cmd(ffmpeg, src, out_webm, "webm")
    assert "libvpx-vp9" in cmd_webm
    assert "libopus" in cmd_webm


def test_build_ffmpeg_convert_cmd_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported target format"):
        build_ffmpeg_convert_cmd(Path("ffmpeg"), tmp_path / "a.mp4", tmp_path / "a.xyz", "xyz")


def test_convert_media_file_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        convert_media_file(tmp_path / "does_not_exist.mp4", "mp3")


@patch("universal_downloader.converter.ensure_ffmpeg", return_value=None)
@patch("universal_downloader.converter.find_ffmpeg", return_value=None)
def test_convert_media_file_missing_ffmpeg(_mock_find: MagicMock, _mock_ensure: MagicMock, tmp_path: Path) -> None:
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"mkv")
    with pytest.raises(DependencyError, match="FFmpeg is required"):
        convert_media_file(src, "mp3")


@patch("universal_downloader.converter.subprocess.run")
def test_convert_media_file_success_and_error(mock_run: MagicMock, tmp_path: Path) -> None:
    src = tmp_path / "recording.mkv"
    src.write_bytes(b"mkv-data")

    def _fake_ok(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"mp3-data")
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        return m

    mock_run.side_effect = _fake_ok
    out = convert_media_file(src, "mp3", ffmpeg_path=Path("ffmpeg"))
    assert out.suffix == ".mp3"
    assert out.exists()

    # Failure case
    mock_run.side_effect = None
    fail_proc = MagicMock()
    fail_proc.returncode = 1
    fail_proc.stderr = "Invalid data found"
    fail_proc.stdout = ""
    mock_run.return_value = fail_proc

    with pytest.raises(DownloadError, match="Invalid data found"):
        convert_media_file(src, "flac", ffmpeg_path=Path("ffmpeg"))


@patch("universal_downloader.cli.convert_media_file")
def test_cli_convert_audio_and_local_remux(
    mock_convert: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "lecture.mp4"
    src.write_bytes(b"data")
    dest = tmp_path / "lecture.mp3"
    mock_convert.return_value = dest

    with patch("sys.argv", ["downloader.py", "--convert-audio", "mp3", str(src), "--json"]):
        code = main()

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["format"] == "mp3"
    assert data["output"] == str(dest)

    # Local file with --remux-video triggers lossless remux_only=True
    remux_dest = tmp_path / "lecture.mkv"
    mock_convert.return_value = remux_dest
    with patch("sys.argv", ["downloader.py", "--remux-video", "mkv", str(src), "--json"]):
        code2 = main()

    assert code2 == 0
    assert mock_convert.call_args.kwargs.get("remux_only") is True


def test_build_ffmpeg_gif_and_frame_and_clip_cmds(tmp_path: Path) -> None:
    from universal_downloader.converter import (
        build_ffmpeg_clip_cmd,
        build_ffmpeg_frame_cmd,
        build_ffmpeg_gif_cmd,
    )

    ffmpeg = Path("ffmpeg")
    src = tmp_path / "vid.mp4"
    gif_out = tmp_path / "vid.gif"
    frame_out = tmp_path / "frame.png"
    clip_out = tmp_path / "clip.mp4"

    gif_cmd = build_ffmpeg_gif_cmd(ffmpeg, src, gif_out, start_time="00:00:05", duration="3", fps=20, width=320)
    assert "-ss" in gif_cmd and "00:00:05" in gif_cmd
    assert "-t" in gif_cmd and "3" in gif_cmd
    assert "fps=20,scale=320:-1:flags=lanczos" in " ".join(gif_cmd)
    assert "palettegen" in " ".join(gif_cmd)

    frame_cmd = build_ffmpeg_frame_cmd(ffmpeg, src, frame_out, timestamp="00:01:23")
    assert "-ss" in frame_cmd and "00:01:23" in frame_cmd
    assert "-vframes" in frame_cmd and "1" in frame_cmd

    clip_cmd = build_ffmpeg_clip_cmd(ffmpeg, src, clip_out, start_time="00:00:10", end_time="00:00:20")
    assert "-ss" in clip_cmd and "00:00:10" in clip_cmd
    assert "-to" in clip_cmd and "00:00:20" in clip_cmd
    assert "copy" in clip_cmd


@patch("universal_downloader.converter.subprocess.run")
def test_video_to_gif_and_extract_frame_execution(mock_run: MagicMock, tmp_path: Path) -> None:
    from universal_downloader.converter import extract_frame, video_to_gif

    src = tmp_path / "test.mp4"
    src.write_bytes(b"sample video bytes")

    def _fake_run(cmd, **_kwargs):
        out_file = Path(cmd[-1])
        out_file.write_bytes(b"dummy image output")
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        return res

    mock_run.side_effect = _fake_run

    gif_path = video_to_gif(src, fps=12, width=360, ffmpeg_path=Path("ffmpeg"))
    assert gif_path.suffix == ".gif"
    assert gif_path.exists()

    frame_path = extract_frame(src, timestamp="00:00:02", ffmpeg_path=Path("ffmpeg"))
    assert frame_path.suffix == ".png"
    assert frame_path.exists()

