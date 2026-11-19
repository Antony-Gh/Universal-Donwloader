"""Tests for new enhancements: slicing, streaming JSON, codec preference, protocol cleaning."""

import json
from io import StringIO
import sys

from universal_downloader.extractor import parse_timestamp_seconds
from universal_downloader.formats import quality_to_selector
from universal_downloader.models import AppConfig
from universal_downloader.progress import ProgressRenderer, emit_json_event
from universal_downloader.protocol import clean_protocol_url
from universal_downloader.updater import get_installed_ytdlp_version


def test_parse_timestamp_seconds():
    assert parse_timestamp_seconds("01:30:15") == 5415.0
    assert parse_timestamp_seconds("03:15") == 195.0
    assert parse_timestamp_seconds("90") == 90.0
    assert parse_timestamp_seconds("*01:10") == 70.0
    assert parse_timestamp_seconds(None) is None
    assert parse_timestamp_seconds("invalid") is None


def test_prefer_codec_selector():
    # H.264
    sel_h264 = quality_to_selector("best", audio_only=False, prefer_codec="h264")
    assert "vcodec^=avc1" in sel_h264

    # VP9
    sel_vp9 = quality_to_selector("1080p", audio_only=False, prefer_codec="vp9")
    assert "vcodec^=vp9" in sel_vp9

    # AV1
    sel_av1 = quality_to_selector("720p", audio_only=False, prefer_codec="av1")
    assert "vcodec^=av01" in sel_av1


def test_clean_protocol_url():
    assert clean_protocol_url("downloader://https://youtube.com/watch?v=123") == "https://youtube.com/watch?v=123"
    assert clean_protocol_url("downloader:https://x.com/status/456") == "https://x.com/status/456"
    assert clean_protocol_url("https://youtube.com/watch?v=123") == "https://youtube.com/watch?v=123"


def test_json_streaming_progress(capsys):
    cfg = AppConfig(json_stream=True)
    renderer = ProgressRenderer(cfg)

    # Trigger downloading hook
    renderer(
        {
            "status": "downloading",
            "downloaded_bytes": 524288,
            "total_bytes": 1048576,
            "speed": 262144,
            "eta": 2,
            "filename": "video.mp4",
        }
    )

    captured = capsys.readouterr().out
    assert captured.strip() != ""
    event = json.loads(captured.strip())
    assert event["event"] == "progress"
    assert event["percent"] == 50.0
    assert event["downloaded_bytes"] == 524288
    assert event["total_bytes"] == 1048576


def test_emit_json_event(capsys):
    emit_json_event("complete", {"url": "https://test.com", "files": ["a.mp4"]})
    captured = capsys.readouterr().out
    data = json.loads(captured.strip())
    assert data["event"] == "complete"
    assert data["files"] == ["a.mp4"]


def test_emit_json_event_pipe_resilience(monkeypatch):
    import sys
    def broken_write(_):
        raise OSError(22, "Invalid argument")
    monkeypatch.setattr(sys.stdout, "write", broken_write)
    # Must not raise exception
    emit_json_event("progress", {"percent": 50.0})


def test_progress_renderer_rate_limiting():
    from universal_downloader.models import AppConfig
    cfg = AppConfig(json_stream=True)
    renderer = ProgressRenderer(cfg)

    events = []
    import universal_downloader.progress as prog
    old_emit = prog.emit_json_event
    try:
        prog.emit_json_event = lambda event_type, payload: events.append((event_type, payload))

        # First call should emit
        renderer({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 1000})
        assert len(events) == 1

        # Immediate second call within 80ms should be throttled
        renderer({"status": "downloading", "downloaded_bytes": 200, "total_bytes": 1000})
        assert len(events) == 1

        # 100% call should emit immediately
        renderer({"status": "downloading", "downloaded_bytes": 1000, "total_bytes": 1000})
        assert len(events) == 2
    finally:
        prog.emit_json_event = old_emit


def test_installed_ytdlp_version():
    ver = get_installed_ytdlp_version()
    assert ver != "not installed"
    assert len(ver) > 0


def test_cross_platform_notify(monkeypatch):
    from universal_downloader.notify import send_notification
    # Notification shouldn't crash regardless of platform
    res = send_notification("Test Title", "Test Message", sound=False)
    assert isinstance(res, bool)


def test_cross_platform_watcher():
    from universal_downloader.watcher import get_clipboard_text
    # Clipboard query shouldn't crash
    val = get_clipboard_text()
    assert val is None or isinstance(val, str)


def test_protocol_registration_dry_run(monkeypatch, tmp_path):
    from universal_downloader.protocol import register_protocol, unregister_protocol
    # Ensure protocol registration and clean up run safely
    dummy_exe = tmp_path / "dummy_downloader.py"
    dummy_exe.write_text("# dummy", encoding="utf-8")
    
    # Run unregister first to test safe deletion
    ok, msg = unregister_protocol()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_youtube_extractor_uses_valid_clients_without_missing_pot(tmp_path):
    from universal_downloader.config import AppConfig
    from universal_downloader.extractor import YTDLPExtractor
    from universal_downloader.models import Platform

    extractor = YTDLPExtractor(AppConfig(output_dir=tmp_path))

    # Base options and attempt 1 must rely on yt-dlp's native defaults (no deprecated tv_embedded or missing_pot)
    base = extractor.base_options()
    assert "extractor_args" not in base
    assert extractor.platform_extra_options(Platform.YOUTUBE, attempt=1) == {}

    # Fallback attempts must never include deprecated 'tv_embedded' or 'missing_pot'
    for attempt in (2, 3, 4):
        opts = extractor.platform_extra_options(Platform.YOUTUBE, attempt=attempt)
        yt_args = opts["extractor_args"]["youtube"]
        assert "tv_embedded" not in yt_args["player_client"]
        assert "formats" not in yt_args

    # Authenticated config selects cookie-supporting clients on fallback
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    authed_extractor = YTDLPExtractor(AppConfig(output_dir=tmp_path, cookies_file=cookie_file))
    authed_clients = authed_extractor.platform_extra_options(Platform.YOUTUBE, attempt=2)["extractor_args"]["youtube"]["player_client"]
    assert "tv_downgraded" in authed_clients
    assert "tv_simply" not in authed_clients


def test_youtube_http_403_triggers_client_rotation_retry(monkeypatch, tmp_path):
    from universal_downloader.config import AppConfig
    from universal_downloader.engine import DownloadEngine
    from universal_downloader.exceptions import DownloadError
    from universal_downloader.models import DownloadResult

    engine = DownloadEngine(AppConfig(output_dir=tmp_path, retries=2, no_history=True))
    attempts: list[int] = []

    def fake_download_once(target, attempt=1):
        attempts.append(attempt)
        if attempt == 1:
            raise DownloadError("unable to download video data: HTTP Error 403: Forbidden")
        dummy_file = tmp_path / "video.mp4"
        dummy_file.write_bytes(b"ok")
        return DownloadResult(success=True, url=target.normalized_url, files=[dummy_file], metadata={"title": "Test"})

    monkeypatch.setattr(engine, "download_once", fake_download_once)
    monkeypatch.setattr("universal_downloader.engine.time.sleep", lambda _s: None)

    res = engine.download("https://youtu.be/t1m2-tt09zI")
    assert res.success is True
    assert attempts == [1, 2]


