# Universal Media Downloader

A production-grade, highly resilient command-line and backend media downloader for publicly accessible media that you are authorized to download. Powered by `yt-dlp` with built-in path boundary safety, secret redaction, format selection, concurrent batch processing, audio transcoding, subtitle embedding, public profile picture resolution, SQLite history tracking, and a real-time JSON stream engine designed for external C#/.NET or native GUI frontends.

---

## Key Features

- **Broad Platform Support**: YouTube, Instagram, TikTok, Twitter/X, Threads, Reddit, Pinterest, Facebook, Vimeo, Twitch, SoundCloud, Bilibili, Bluesky, Bandcamp, Loom, and generic video feeds.
- **Fast Multi-Fragment Downloads**: Multi-threaded fragment downloading (`--concurrent-fragments 4` or higher) speeds up DASH and HLS video streams by 4x to 10x.
- **Video Time-Range Slicing**: Download specific segments (e.g. `--download-sections "*00:01:30-00:03:00"` or `--start-time "00:01:30" --end-time "00:03:00"`) without fetching the entire video first.
- **Codec Preferences**: Prefer specific video codecs like `--prefer-codec h264` (for hardware acceleration compatibility on Windows), `vp9`, `av01`, or `hevc`.
- **Audio Extraction**: Extract audio in `best` (lossless native stream without re-encoding), `mp3`, `m4a`, `flac`, `opus`, `wav`, or `aac` with customizable bitrates (`320k`, `192k`, VBR).
- **Embedded Metadata & Artwork**: Embed title, artist, date, chapters, and cover art (`--embed-metadata`, `--embed-thumbnail`) directly into MP4/MP3/M4A containers, or save raw artwork files with `--write-thumbnail`.
- **Subtitles & Captions**: Download separate subtitle files (`--write-subs`) or embed them into the video (`--embed-subs`), supporting language codes (`--sub-langs "en,es"`) and auto-generated captions (`--auto-subs`).
- **SQLite Download History**: Automatically records all completed and failed downloads with titles, uploaders, file paths, and dates in an indexed SQLite database (`downloads.db`). Queryable via `--history` and `--history-search`.
- **Real-Time JSON Streaming for External GUIs**: The `--json-stream` flag emits line-delimited JSON events to stdout for real-time progress, speed, ETA, and status, making integration with C# (WPF/WinUI 3/Avalonia) or Rust/Go frontends straightforward.
- **Clipboard Watcher Daemon**: Run `--watch-clipboard` to monitor the system clipboard (Win32 API on Windows, `wl-paste`/`xclip`/`xsel` on Linux, `pbpaste` on macOS) and automatically enqueue or download media links as soon as they are copied.
- **Desktop Notifications & Audio Alerts**: Send native desktop alerts and audio cues (`--notify`) when downloads complete across Windows (Windows Runtime Toast), Linux (`notify-send`), and macOS (`osascript`).
- **Cross-Platform URL Scheme**: Register `downloader://` with `--register-protocol` across Windows Registry and Linux FreeDesktop XDG handlers so browser bookmarklets or desktop hyperlinks launch downloads directly.
- **Self-Updater**: Run `--update` to check and upgrade `yt-dlp` to the latest PyPI release in one command.
- **Resilient Batch Processing**:
  - Multi-threaded concurrent batch downloads (`--concurrency 4`).
  - Polite scraping delays with jitter (`--sleep-interval 3 --max-sleep-interval 7`).
  - Idempotent runs with download archives (`--download-archive archive.txt`).
- **Security by Design**: Enforces directory confinement (`ensure_inside_directory`), prevents path traversal, sanitizes Windows-reserved filenames (`CON`, `PRN`, etc.), and redacts sensitive credentials from logs.

---

## Installation & Prerequisites

### 1. Python
Requires **Python 3.10+**.

```bash
git clone https://github.com/your-username/Universal_Downloader.git
cd Universal_Downloader
pip install -r requirements.txt
```

Or install in editable mode:
```bash
pip install -e .
```

### 2. FFmpeg (Recommended)
FFmpeg is required for merging high-res streams, audio conversion, subtitle embedding, time slicing, and metadata tagging.

- **Windows**: `winget install Gyan.FFmpeg` or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and add `bin` to your `PATH`.
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 3. JavaScript Runtime (Optional)
Having `node` or `deno` on your `PATH` allows yt-dlp to solve advanced player challenges (e.g. YouTube n-sig extraction).

---

## CLI Usage & Examples

### Basic Downloads
```bash
# Download highest quality video + audio
python downloader.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Download in 1080p with H.264 codec (optimal Windows hardware playback)
python downloader.py --quality 1080p --prefer-codec h264 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# List available formats without downloading
python downloader.py --formats "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Time-Range Slicing
```bash
# Download only from 1m30s to 3m00s of a video
python downloader.py --download-sections "*00:01:30-00:03:00" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Slicing with start and end times
python downloader.py --start-time "00:00:45" --end-time "00:02:15" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### High-Speed Fragment Downloading
```bash
# Download 8 DASH fragments simultaneously for maximum speed
python downloader.py --concurrent-fragments 8 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Audio Extraction & Tagging
```bash
# Extract as MP3 at 320 kbps with embedded metadata and artwork
python downloader.py --audio-only --audio-format mp3 --audio-quality 320k --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Lossless audio extraction (keeps original AAC/Opus stream without transcoding)
python downloader.py --audio-only --audio-format best "https://soundcloud.com/artist/track"
```

### Subtitles & Remuxing
```bash
# Embed English and Spanish subtitles into the video
python downloader.py --embed-subs --sub-langs "en,es" --auto-subs "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Remux to MP4 container and remove YouTube sponsor segments
python downloader.py --remux-video mp4 --sponsorblock-remove "sponsor,intro" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Split long video into separate chapter files
python downloader.py --split-chapters "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### SQLite History Management
```bash
# Show recent 20 downloads
python downloader.py --history

# Search download history by title, artist, or URL
python downloader.py --history-search "tutorial"

# Export history as JSON
python downloader.py --history --json

# Clear history database
python downloader.py --history-clear
```

### Batch Downloads
```bash
# Multi-threaded batch download (3 workers) with download archive to skip duplicates
python downloader.py --batch urls.txt --concurrency 3 --download-archive history.txt --limit-rate 5M
```

### System Integration & Automation
```bash
# Run clipboard monitor: automatically downloads media URLs when copied
python downloader.py --watch-clipboard

# Register downloader:// protocol in Windows Registry (for browser bookmarklets)
python downloader.py --register-protocol

# Enable Windows desktop notification on completion
python downloader.py --notify "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Update yt-dlp to latest release
python downloader.py --update
```

---

## External GUI Integration (C# / .NET / WinUI / WPF)

The backend provides `--json-stream` specifically designed for native C# (WPF, WinUI 3, Avalonia, or MAUI) and Go/Rust desktop frontends. 

When invoked with `--json-stream`, the process writes line-delimited JSON events to `stdout`:

```bash
python downloader.py --json-stream "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Stream Events Format

1. **Progress Event:**
```json
{"event": "progress", "status": "downloading", "downloaded_bytes": 1048576, "total_bytes": 10485760, "percent": 10.0, "speed": 1048576, "eta": 9, "filename": "video.mp4"}
```
2. **Post-processing Event:**
```json
{"event": "postprocess", "status": "processing"}
```
3. **Completion Event:**
```json
{"event": "complete", "url": "https://...", "files": ["downloads/youtube/video.mp4"], "title": "Video Title", "uploader": "Creator"}
```
4. **Error Event:**
```json
{"event": "error", "url": "https://...", "error": "Description of failure"}
```

### C# Integration Example

```csharp
using System;
using System.Diagnostics;
using System.Text.Json;

var process = new Process
{
    StartInfo = new ProcessStartInfo
    {
        FileName = "python",
        Arguments = "downloader.py --json-stream \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"",
        RedirectStandardOutput = true,
        UseShellExecute = false,
        CreateNoWindow = true
    }
};

process.OutputDataReceived += (sender, e) =>
{
    if (string.IsNullOrWhiteSpace(e.Data)) return;

    try
    {
        using var doc = JsonDocument.Parse(e.Data);
        var root = doc.RootElement;
        string eventType = root.GetProperty("event").GetString();

        if (eventType == "progress")
        {
            double percent = root.GetProperty("percent").GetDouble();
            long speed = root.GetProperty("speed").GetInt64();
            Console.WriteLine($"Progress: {percent:F1}% at {speed / 1024 / 1024.0:F2} MB/s");
        }
        else if (eventType == "complete")
        {
            Console.WriteLine("Download finished successfully!");
        }
    }
    catch (JsonException) { }
};

process.Start();
process.BeginOutputReadLine();
process.WaitForExit();
```

### Building Standalone Executable (PyInstaller)

To ship a self-contained `downloader.exe` binary so users do not need Python or dependencies installed:

```bash
# Automatically installs PyInstaller if needed and compiles downloader.exe into dist/
python build_exe.py
```

The resulting `dist/downloader.exe` is a single standalone executable that supports all CLI arguments and real-time `--json-stream` events.

---

## One-Click Multi-OS Build & GitHub Release Publisher

To compile the entire project (Python backend + C# Avalonia + C# WPF) into standalone executables for **Windows**, **Linux**, and **macOS**, and publish them directly to GitHub Releases in one command:

```bash
# Compile and publish release v1.1.0 to GitHub
python build_and_publish.py -v 1.1.0

# Or build and package all OS archives locally without uploading
python build_and_publish.py --no-publish
```

### What It Does:
1. **Compiles Standalone Python Engine**: Packages `downloader` via PyInstaller with the custom high-resolution application icon.
2. **Publishes Native .NET 9 Frontends**: Compiles self-contained, single-file executables for:
   - `win-x64` (Windows Avalonia & WPF apps)
   - `linux-x64` (Linux Wayland & X11 binary)
   - `osx-x64` (macOS Intel binary)
   - `osx-arm64` (macOS Apple Silicon binary)
3. **Creates Distribution Archives & Checksums**:
   - `UniversalDownloader-v1.1.0-windows-x64.zip`
   - `UniversalDownloader-v1.1.0-linux-x64.tar.gz`
   - `UniversalDownloader-v1.1.0-macos-x64.tar.gz`
   - `UniversalDownloader-v1.1.0-macos-arm64.tar.gz`
   - `SHA256SUMS.txt`
4. **Automated GitHub Release Publishing**:
   - Tags the repository and pushes to GitHub.
   - Publishes the GitHub Release via `gh` CLI or GitHub REST API with formatted changelog notes.
   - Automatically triggers the cloud CI/CD matrix workflow ([.github/workflows/release.yml](file:///e:/Projects/Universal_Downloader/.github/workflows/release.yml)) for native cloud builds on genuine Windows, Ubuntu, and macOS runners.

---

## C# .NET Desktop Application Suite

The project includes a complete .NET 9 solution (`UniversalDownloader.sln`) with:

1. **`UniversalDownloader.Core`**:
   - Cross-platform class library (.NET 9) with strongly-typed models (`DownloadProgressEvent`, `DownloadCompleteEvent`, `FormatInfoModel`, `HistoryRecordModel`, `DownloadOptions`).
   - `DownloaderClient`: Asynchronous IPC client that automatically locates either compiled binaries (`downloader.exe` or `downloader`) or `downloader.py` (via `python` or `python3`), spawns the process in background, and streams real-time events.
   - `PlatformUtils`: Unified cross-platform helpers for launching system file viewers (`xdg-open`, `open`, `explorer.exe`), opening containing folders, and resolving binaries.
2. **`UniversalDownloader.Avalonia`**:
   - Cross-platform modern desktop application built on **Avalonia 11** (.NET 9).
   - Runs seamlessly on **Windows, Linux (Wayland & X11), and macOS**.
   - Features real-time animated progress bars, speed and ETA indicators, format inspection, paste shortcuts, and a full SQLite download history browser with "▶ Play" and "📁 Folder" buttons.
3. **`UniversalDownloader.App`**:
   - Native Windows desktop app built with **WPF** (.NET 9).

### Building & Running the C# Desktop Apps

#### Cross-Platform (Windows, Linux, macOS) — Avalonia UI:
```bash
# Build and run the cross-platform Avalonia desktop app
dotnet build src/UniversalDownloader.Avalonia/UniversalDownloader.Avalonia.csproj
dotnet run --project src/UniversalDownloader.Avalonia/UniversalDownloader.Avalonia.csproj
```

#### Windows Only — WPF App:
```bash
# Build and run the Windows-native WPF application
dotnet build src/UniversalDownloader.App/UniversalDownloader.App.csproj
dotnet run --project src/UniversalDownloader.App/UniversalDownloader.App.csproj
```

---

## Configuration

Settings can be defined via CLI arguments, `.env` file, or `config.json`. Generate starter configuration templates using:

```bash
python downloader.py --init-config
```

---

## Testing

Run the test suite using `pytest`:

```bash
pytest -v
```

All 43 unit and integration tests run in ~1.2 seconds across platforms.

---

## Legal & Compliance Notice

Universal Media Downloader is designed for educational, archiving, and research purposes on **publicly accessible content** that the user is authorized to download. It does not circumvent digital rights management (DRM), bypass paywalls, extract private credentials, or solve CAPTCHAs. Always respect copyright laws and platform terms of service.

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
