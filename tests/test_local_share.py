import urllib.request
from pathlib import Path
import pytest

from universal_downloader.local_share import (
    get_local_ip,
    format_size,
    generate_qr_ascii,
    start_file_share,
)


def test_get_local_ip():
    ip = get_local_ip()
    assert isinstance(ip, str)
    assert len(ip.split(".")) == 4


def test_format_size():
    assert format_size(500) == "500.0 B"
    assert "KB" in format_size(2048)
    assert "MB" in format_size(5 * 1024 * 1024)
    assert "GB" in format_size(3 * 1024 * 1024 * 1024)


def test_generate_qr_ascii():
    qr = generate_qr_ascii("http://192.168.1.100:8080/")
    assert isinstance(qr, str)
    assert len(qr) > 20


def test_file_share_http_server(tmp_path: Path):
    test_file = tmp_path / "hello.txt"
    test_file.write_text("Hello from local file share!", encoding="utf-8")

    server = start_file_share(test_file, port=0)
    # Bypass any system/environment HTTP_PROXY for localhost loopback testing
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        assert server.actual_port > 0
        base_url = f"http://127.0.0.1:{server.actual_port}"

        # 1. Landing page
        with opener.open(f"{base_url}/", timeout=5) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "hello.txt" in html
            assert "Download to Device" in html

        # 2. File download
        with opener.open(f"{base_url}/download", timeout=5) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert content == "Hello from local file share!"
            assert "attachment" in resp.headers.get("Content-Disposition", "")
    finally:
        server.stop()
