import pytest
from unittest.mock import MagicMock, patch
from universal_downloader.cli import run_quick_hud
from universal_downloader.config import AppConfig


def test_quick_hud_with_clipboard_url():
    mock_engine = MagicMock()
    mock_engine.download.return_value = MagicMock(successful=True)
    config = AppConfig()

    with patch("universal_downloader.cli.get_clipboard_text", return_value="https://www.youtube.com/watch?v=sample123"), \
         patch("builtins.input", side_effect=["y", "1"]):
        ret = run_quick_hud(mock_engine, config)

    assert ret == 0
    assert config.format == "video"
    mock_engine.download.assert_called_once_with("https://www.youtube.com/watch?v=sample123", config=config)


def test_quick_hud_audio_choice():
    mock_engine = MagicMock()
    mock_engine.download.return_value = MagicMock(successful=True)
    config = AppConfig()

    with patch("universal_downloader.cli.get_clipboard_text", return_value=""), \
         patch("builtins.input", side_effect=["https://soundcloud.com/artist/track", "2"]):
        ret = run_quick_hud(mock_engine, config)

    assert ret == 0
    assert config.format == "audio"
    mock_engine.download.assert_called_once_with("https://soundcloud.com/artist/track", config=config)


def test_quick_hud_preset_choice():
    mock_engine = MagicMock()
    mock_engine.download.return_value = MagicMock(successful=True)
    config = AppConfig()

    with patch("universal_downloader.cli.get_clipboard_text", return_value=""), \
         patch("builtins.input", side_effect=["https://vimeo.com/12345", "3"]):
        ret = run_quick_hud(mock_engine, config)

    assert ret == 0
    assert config.preset == "discord"
    mock_engine.download.assert_called_once_with("https://vimeo.com/12345", config=config)
