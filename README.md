# Universal Media Downloader

A production-grade, highly resilient command-line downloader for publicly accessible media that you are authorized to download. Powered by `yt-dlp` with built-in path boundary safety, secret redaction, format selection, concurrent batch processing, audio transcoding, subtitle embedding, and public profile picture resolution.

---

## Key Features

- **Broad Platform Support**: YouTube, Instagram, TikTok, Twitter/X, Threads, Reddit, Pinterest, Facebook, Vimeo, Twitch, SoundCloud, Bilibili, Bluesky, Bandcamp, Loom, and generic video feeds.
- **Audio Extraction**: Extract audio in `best` (lossless native stream without re-encoding), `mp3`, `m4a`, `flac`, `opus`, `wav`, or `aac` with customizable bitrates (`320k`, `192k`, VBR).
- **Embedded Metadata & Artwork**: Embed title, artist, date, chapters, and cover art (`--embed-metadata`, `--embed-thumbnail`) directly into MP4/MP3/M4A containers.
- **Subtitles & Captions**: Download separate subtitle files (`--write-subs`) or embed them into the video (`--embed-subs`), supporting specific language codes (`--sub-langs "en,es"`) and auto-generated captions (`--auto-subs`).
- **Resilient Batch Processing**:
  - Multi-threaded concurrent downloads (`--concurrency 4`).
  - Polite scraping delays with jitter (`--sleep-interval 3 --max-sleep-interval 7`).
  - Idempotent runs with download archives (`--download-archive archive.txt`) to skip already downloaded items.
- **Smart Retries & Error Guidance**: Exponential backoff for transient issues (including HTTP 429 rate limits), automated TikTok unblocking retries, and actionable diagnosis for YouTube bot verification and Chromium App-Bound Encryption.
- **Security by Design**: Enforces directory confinement (`ensure_inside_directory`), prevents path traversal, sanitizes Windows-reserved filenames (`CON`, `PRN`, etc.), and redacts sensitive credentials from logs.
- **Developer-Friendly**: Supports `--dry-run` simulation, machine-readable `--json` output, and `--init-config` starter generation.

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

FFmpeg is required for merging high-res video/audio streams, audio conversion, subtitle embedding, and metadata tagging.

- **Windows**: `winget install Gyan.FFmpeg` or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and add `bin` to your `PATH`.
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 3. JavaScript Runtime (Optional)

Having `node` or `deno` on your `PATH` allows yt-dlp to automatically solve advanced player challenges (e.g. YouTube n-sig extraction).

---

## CLI Usage & Examples

### Basic Downloads

```bash
# Download highest quality video + audio
python downloader.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Download specific resolution
python downloader.py --quality 1080p "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# List available formats without downloading
python downloader.py --formats "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Audio Extraction

```bash
# Extract as MP3 at 320 kbps with embedded metadata and artwork
python downloader.py --audio-only --audio-format mp3 --audio-quality 320k --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Keep original audio stream without re-encoding (lossless)
python downloader.py --audio-only --audio-format best "https://soundcloud.com/artist/track"
```

### Subtitles & Video Postprocessing

```bash
# Embed English and Spanish subtitles into the video
python downloader.py --embed-subs --sub-langs "en,es" --auto-subs "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Remux to MP4 container and remove YouTube sponsor segments
python downloader.py --remux-video mp4 --sponsorblock-remove "sponsor,intro" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Split long video or podcast into chapter files
python downloader.py --split-chapters "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Playlists

```bash
# Download items 1 through 5 from a playlist
python downloader.py --playlist-items 1-5 "https://www.youtube.com/playlist?list=PL123456789"

# Download at most 10 items
python downloader.py --max-downloads 10 "https://www.youtube.com/playlist?list=PL123456789"
```

### Batch Downloads

Create a text file `urls.txt` with one URL per line:

```text
https://www.youtube.com/watch?v=video1
https://www.instagram.com/reel/video2/
https://www.tiktok.com/@user/video/video3
```

Execute with parallel workers, rate limiting, and an archive file:

```bash
python downloader.py --batch urls.txt --concurrency 3 --download-archive history.txt --limit-rate 5M
```

For polite single-threaded batching with random sleep delays:

```bash
python downloader.py --batch urls.txt --sleep-interval 3 --max-sleep-interval 8
```

### Public Profile Photos

```bash
# Download public profile avatar
python downloader.py --profile "https://www.instagram.com/natgeo/"

# Platform-shorthand syntax
python downloader.py --profile instagram:natgeo
python downloader.py --profile tiktok:khaby.lame
python downloader.py --profile x:nasa
```

### Cookies & Proxy

```bash
# Pass cookies from browser profile
python downloader.py --cookies-from-browser chrome "https://example.com/video"

# Pass Netscape cookies file
python downloader.py --cookies cookies.txt "https://example.com/video"

# Use HTTP or SOCKS5 proxy
python downloader.py --proxy "socks5://127.0.0.1:9050" "https://example.com/video"
```

### Developer & Automation Flags

```bash
# Dry run: inspect and preview metadata without downloading
python downloader.py --dry-run "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Machine-readable JSON output to stdout
python downloader.py --json "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Initialize starter configuration files
python downloader.py --init-config
```

---

## Configuration

Settings can be defined via CLI arguments, `.env` file, or `config.json`. CLI flags take the highest precedence.

Generate template configuration files:

```bash
python downloader.py --init-config
```

### Example `config.json`

```json
{
  "download_dir": "downloads",
  "log_dir": "logs",
  "retries": 3,
  "timeout": 30,
  "quality": "best",
  "audio_only": false,
  "audio_format": "mp3",
  "audio_quality": "192k",
  "write_metadata": true,
  "embed_metadata": false,
  "embed_thumbnail": false,
  "write_subs": false,
  "embed_subs": false,
  "sub_langs": "en",
  "concurrency": 1,
  "limit_rate": null,
  "sleep_interval": 0,
  "proxy": null,
  "geo_bypass": false
}
```

---

## Project Structure

```text
Universal_Downloader/
├── downloader.py                  # CLI entry point & backward-compatible module
├── pyproject.toml                 # Package metadata and console entry point
├── requirements.txt               # Dependencies
├── README.md                      # Documentation
├── universal_downloader/          # Core package
│   ├── __init__.py                # Package metadata & version
│   ├── cli.py                     # Argument parser & interactive mode
│   ├── engine.py                  # Orchestration, retry loops & download execution
│   ├── extractor.py               # yt-dlp option assembly & process execution
│   ├── batch.py                   # Serial & concurrent batch task execution
│   ├── config.py                  # Dotenv, JSON & CLI config merger
│   ├── models.py                  # Enums, dataclasses, and AppConfig
│   ├── formats.py                 # Format parser and quality selectors
│   ├── profile.py                 # Public profile image resolution
│   ├── progress.py                # Terminal progress bar rendering
│   ├── console.py                 # ANSI colors and banner display
│   ├── logging_utils.py           # Secret filters, error formatters & predicates
│   ├── exceptions.py              # Application exception hierarchy
│   └── utils/
│       ├── fs.py                  # Filename sanitization, unique path & path safety
│       └── net.py                 # URL normalization, domain & platform matching
└── tests/                         # Pytest test suite
    ├── test_fs.py
    ├── test_net.py
    ├── test_config.py
    ├── test_formats.py
    ├── test_logging_and_errors.py
    └── test_cli_and_engine.py
```

---

## Testing

Run the test suite using `pytest`:

```bash
pytest -v
```

---

## Legal & Compliance Notice

Universal Media Downloader is designed for educational, archiving, and research purposes on **publicly accessible content** that the user is authorized to download. It does not circumvent digital rights management (DRM), bypass paywalls, extract private credentials, or solve CAPTCHAs. Always respect copyright laws and platform terms of service.
