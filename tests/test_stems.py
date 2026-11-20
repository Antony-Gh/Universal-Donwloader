import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from universal_downloader.stems import separate_stems


def test_separate_stems_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        separate_stems(tmp_path / "non_existent.mp3")


def test_separate_stems_ffmpeg_mocked(tmp_path):
    source_file = tmp_path / "song.mp3"
    source_file.write_text("dummy mp3 content")

    inst_file = tmp_path / "song_instrumental.mp3"
    voc_file = tmp_path / "song_vocals.mp3"

    def fake_ffmpeg_run(cmd, **kwargs):
        # Create output file specified in cmd[-1]
        out_path = Path(cmd[-1])
        out_path.write_text("dummy stem")
        return MagicMock(returncode=0, stderr="")

    with patch("universal_downloader.stems.shutil.which", return_value=None), \
         patch("universal_downloader.stems.find_ffmpeg", return_value=Path("ffmpeg")), \
         patch("subprocess.run", side_effect=fake_ffmpeg_run):

        # Test both stems
        stems = separate_stems(source_file, output_dir=tmp_path, mode="both")
        assert "instrumental" in stems
        assert "vocals" in stems
        assert stems["instrumental"].is_file()
        assert stems["vocals"].is_file()

        # Test karaoke only
        stems_karaoke = separate_stems(source_file, output_dir=tmp_path, mode="karaoke")
        assert "instrumental" in stems_karaoke
        assert "vocals" not in stems_karaoke


def test_separate_stems_demucs_mocked(tmp_path):
    source_file = tmp_path / "test_track.wav"
    source_file.write_text("dummy wav")

    def fake_demucs_run(cmd, **kwargs):
        # Demucs output structure: out_folder / htdemucs / stem_name / (vocals.wav, no_vocals.wav)
        out_dir = Path(cmd[3]) / "htdemucs" / source_file.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "vocals.wav").write_text("vocals")
        (out_dir / "no_vocals.wav").write_text("no_vocals")
        return MagicMock(returncode=0)

    with patch("universal_downloader.stems.shutil.which", return_value="/usr/bin/demucs"), \
         patch("subprocess.run", side_effect=fake_demucs_run):

        stems = separate_stems(source_file, output_dir=tmp_path, mode="both")
        assert "instrumental" in stems
        assert "vocals" in stems
        assert stems["instrumental"].name == "test_track_instrumental.wav"
        assert stems["vocals"].name == "test_track_vocals.wav"
