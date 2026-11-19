"""Local network file sharing with QR code for quick mobile downloads."""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("universal_downloader.local_share")


def get_local_ip() -> str:
    """Detect the local machine's LAN IP address reachable on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually transmit packets, just routes socket to find preferred outbound interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def format_size(num_bytes: int) -> str:
    """Format bytes into readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def generate_qr_ascii(data: str) -> str:
    """Generate an ASCII QR code for terminal display."""
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)

        output = io.StringIO()
        qr.print_ascii(out=output, invert=True)
        return output.getvalue()
    except Exception:
        # Fallback to text box if qrcode is unavailable
        border = "=" * (len(data) + 6)
        return f"\n{border}\n   {data}\n{border}\n"


class FileShareHandler(BaseHTTPRequestHandler):
    """HTTP handler serving a mobile-friendly download page and direct file stream."""

    server_file: Path

    def log_message(self, format: str, *args: object) -> None:
        """Suppress standard HTTP server access logging unless debugging."""
        LOGGER.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self.serve_landing_page()
        elif path == "/download":
            self.serve_file(as_attachment=True)
        elif path == "/stream":
            self.serve_file(as_attachment=False)
        else:
            self.send_error(404, "Not Found")

    def serve_landing_page(self) -> None:
        target = self.server_file
        if not target.exists():
            self.send_error(404, "Shared file not found")
            return

        filename = target.name
        filesize = format_size(target.stat().st_size)
        mime_type, _ = mimetypes.guess_type(str(target))
        mime_type = mime_type or "application/octet-stream"

        preview_html = ""
        if mime_type.startswith("video/"):
            preview_html = f'<video controls playsinline style="max-width:100%;border-radius:12px;margin:20px 0;"><source src="/stream" type="{mime_type}"></video>'
        elif mime_type.startswith("audio/"):
            preview_html = f'<audio controls style="width:100%;margin:20px 0;"><source src="/stream" type="{mime_type}"></audio>'
        elif mime_type.startswith("image/"):
            preview_html = f'<img src="/stream" style="max-width:100%;border-radius:12px;margin:20px 0;" alt="{filename}">'

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Download {filename}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0d1117;
    color: #e6edf3;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    box-sizing: border-box;
  }}
  .card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 16px;
    padding: 28px;
    max-width: 480px;
    width: 100%;
    box-shadow: 0 16px 32px rgba(0,0,0,0.4);
    text-align: center;
  }}
  .icon {{
    font-size: 48px;
    margin-bottom: 12px;
  }}
  h1 {{
    font-size: 1.25rem;
    word-break: break-all;
    margin: 0 0 8px 0;
  }}
  .size {{
    color: #8b949e;
    font-size: 0.95rem;
    margin-bottom: 16px;
  }}
  .btn {{
    display: block;
    background: #238636;
    color: #ffffff;
    text-decoration: none;
    font-weight: 600;
    font-size: 1.1rem;
    padding: 14px 20px;
    border-radius: 10px;
    transition: background 0.2s;
  }}
  .btn:hover {{
    background: #2ea043;
  }}
  .footer {{
    margin-top: 24px;
    font-size: 0.8rem;
    color: #6e7681;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">📲</div>
  <h1>{filename}</h1>
  <div class="size">File size: <strong>{filesize}</strong></div>
  {preview_html}
  <a class="btn" href="/download" download="{filename}">⬇ Download to Device</a>
  <div class="footer">Transferred securely over your local Wi-Fi via Universal Media Downloader</div>
</div>
</body>
</html>"""
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, as_attachment: bool = True) -> None:
        target = self.server_file
        if not target.exists():
            self.send_error(404, "Shared file not found")
            return

        file_size = target.stat().st_size
        mime_type, _ = mimetypes.guess_type(str(target))
        mime_type = mime_type or "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        if as_attachment:
            quoted = urllib.parse.quote(target.name)
            self.send_header("Content-Disposition", f'attachment; filename="{quoted}"; filename*=UTF-8\'\'{quoted}')
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with target.open("rb") as f:
            while chunk := f.read(64 * 1024):
                self.wfile.write(chunk)


class ShareServer:
    """Manages the lifecycle of a background HTTP sharing server."""

    def __init__(self, file_path: Path, port: int = 0) -> None:
        self.file_path = file_path.resolve()
        if not self.file_path.exists():
            raise FileNotFoundError(f"File to share does not exist: {self.file_path}")

        handler_cls = type("BoundFileShareHandler", (FileShareHandler,), {"server_file": self.file_path})
        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler_cls)
        self.actual_port = self.httpd.server_port
        self.lan_ip = get_local_ip()
        self.url = f"http://{self.lan_ip}:{self.actual_port}/"
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start listening on background daemon thread."""
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        LOGGER.info("Local share server started at %s for %s", self.url, self.file_path.name)

    def stop(self) -> None:
        """Stop server and release port."""
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def start_file_share(file_path: Path, port: int = 0) -> ShareServer:
    """Launch local sharing server and return the instance."""
    server = ShareServer(file_path, port=port)
    server.start()
    return server
