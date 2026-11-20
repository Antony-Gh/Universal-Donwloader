from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from universal_downloader.models import AppConfig
from universal_downloader.presets import (
    AVAILABLE_PRESETS,
    compress_video_to_target_size,
    get_preset,
    get_video_duration,
    list_presets,
)


def test_list_and_get_presets():
    presets = list_presets()
    assert len(presets) >= 4
    ids = {p["id"] for p in presets}
    assert "discord" in ids
    assert "whatsapp" in ids
    assert "car_audio" in ids
    assert "tv_theater" in ids

    discord = get_preset("discord")
    assert discord is not None
    assert discord.max_size_mb == 24.5
    assert discord.target_format == "mp4"

    car = get_preset("CAR_AUDIO")  # case-insensitive
    assert car is not None
    assert car.audio_only is True


def test_compress_video_already_under_limit(tmp_path: Path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"0" * 1024 * 100)  # 100 KB

    res = compress_video_to_target_size(video, target_mb=10.0)
    assert res == video


def test_compress_video_calculates_bitrate(tmp_path: Path):
    video = tmp_path / "large.mp4"
    video.write_bytes(b"0" * 1024 * 1024 * 30)  # 30 MB

    with patch("universal_downloader.presets.ensure_ffmpeg", return_value=Path("ffmpeg")), \
         patch("universal_downloader.presets.get_video_duration", return_value=120.0), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # Mock resulting file
        out_file = tmp_path / "out.mp4"
        out_file.write_bytes(b"0" * 1024 * 1024 * 20)

        res = compress_video_to_target_size(video, output_path=out_file, target_mb=24.5)
        assert res == out_file
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-movflags" in cmd
