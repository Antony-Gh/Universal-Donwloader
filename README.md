# Universal Media Downloader

<p align="center">
  <img src="assets/app-icon.png" alt="Universal Media Downloader Logo" width="128" height="128" />
</p>

<p align="center">
  <strong>The all-in-one, privacy-focused, cross-platform media downloader, converter, and automation suite.</strong>
</p>

<p align="center">
  <a href="https://github.com/Antony-Gh/Universal-Donwloader/releases/latest"><img src="https://img.shields.io/badge/release-v4.0.0-blue.svg?style=flat-square" alt="Latest Release" /></a>
  <a href="https://github.com/Antony-Gh/Universal-Donwloader/actions"><img src="https://img.shields.io/badge/tests-183%20passed-brightgreen.svg?style=flat-square" alt="Tests" /></a>
  <a href="https://dotnet.microsoft.com/download/dotnet/9.0"><img src="https://img.shields.io/badge/.NET-9.0%20(Avalonia%2011)-purple.svg?style=flat-square" alt=".NET 9" /></a>
  <a href="https://developer.android.com/"><img src="https://img.shields.io/badge/Android-8.0%2B%20(Compose)-green.svg?style=flat-square" alt="Android" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-yellow.svg?style=flat-square" alt="Python 3.10+" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-red.svg?style=flat-square" alt="License" /></a>
  <a href="https://github.com/Antony-Gh"><img src="https://img.shields.io/badge/author-Anthony%20Gaius-blueviolet.svg?style=flat-square" alt="Author" /></a>
</p>

---

## 🌟 What is Universal Media Downloader?

**Universal Media Downloader** is a high-resilience, production-grade media downloading suite engineered from the ground up to eliminate common frustrations with online tools: **no ads, no tracking, no suspicious redirects, and no paywalls**. Every feature runs **100% locally** on your device.

Available across **Windows, Linux, macOS, Android (Jetpack Compose), and CLI**, with a companion **Manifest V3 Browser Extension**.

---

## ⚡ v4.0.0 Feature Matrix & Capabilities

| Capability | CLI | Desktop (Avalonia) | Android (Compose) | Details |
| :--- | :---: | :---: | :---: | :--- |
| **Broad Platform Support** | ✅ | ✅ | ✅ | YouTube, TikTok, Instagram, X/Twitter, Reddit, Facebook, Twitch, Vimeo, Bilibili, Bluesky, SoundCloud, Bandcamp, and 1,000+ sites. |
| **🚀 aria2c Acceleration** | ✅ | ✅ | ❌ | Multi-connection engine downloading segmented streams up to **10x faster** (`--aria2`). |
| **🎙️ Local AI Whisper Transcription** | ✅ | ✅ | ❌ | 100% offline speech-to-text. Generates synchronized `.srt`, `.vtt`, and `.txt` summaries (`--whisper`). |
| **📺 Channel & Playlist Subscriptions** | ✅ | ✅ | ✅ | Auto-track creators and channels. Downloads new uploads automatically with custom quality presets. |
| **⏰ Smart Scheduling & Battery Saver** | ✅ | ✅ | ✅ | Queue downloads at set times (e.g. `02:00` off-peak), pause on battery power, and enforce Wi-Fi only. |
| **✂️ Video-to-GIF & Frame Grabber** | ✅ | ✅ | ❌ | High-quality dual-pass palettegen GIFs, millisecond sub-clips, and uncompressed PNG frame capture. |
| **🎵 MusicBrainz & CAA Tagging** | ✅ | ✅ | ❌ | Acoustic fingerprinting and metadata lookup. Embeds accurate artist, album, year, and high-res cover art. |
| **📲 Send to Phone over LAN (LocalShare)** | ✅ | ✅ | ❌ | LocalSend-style direct transfer from PC to phone via animated QR code over home Wi-Fi (`--local-share`). |
| **🔍 Intelligent Duplicate Detection** | ✅ | ✅ | ✅ | Scans target folders before downloading, matching filenames, normalized titles, and IDs to save bandwidth. |
| **🧩 Manifest V3 Browser Extension** | ✅ | ✅ | ❌ | 1-click download popup and real-time page media stream sniffer (.m3u8, .mpd, HTML5 video). |
| **🛡️ In-App Privacy Dashboard & GDPR** | ✅ | ✅ | ✅ | Zero activity tracking, purely anonymous UUIDv4 metrics, and 1-click remote GDPR data wipe. |
| **🖥️ Tray Icon & Clipboard Monitor** | ✅ | ✅ | ✅ | Minimizes to system tray on desktop and detects copied media URLs in background. |
| **👤 Creator & Credits Tab** | ✅ | ✅ | ✅ | Full attribution, author bio, issue reporting, and open-source acknowledgments for Anthony Gaius. |

---

## 📱 Android Installation & Distribution

Because Google Play restricts YouTube downloading apps under section 4.4 of its Developer Agreement, Universal Media Downloader is distributed through trusted open-source channels:

### 1. Obtainium (Recommended for Automated Updates)
[Obtainium](https://github.com/ImranR98/Obtainium) allows you to install and receive seamless background update notifications directly from this GitHub repository.

- Open Obtainium on your Android phone.
- Tap **Add App**.
- Enter URL: `https://github.com/Antony-Gh/Universal-Donwloader`
- Tap **Add** → Obtainium installs and manages automatic background updates.

Or tap this deep-link directly on your mobile device:
> [**📲 Add to Obtainium**](obtainium://add/https://github.com/Antony-Gh/Universal-Donwloader)

### 2. Direct APK Download
Download signed APK packages directly from [GitHub Releases](https://github.com/Antony-Gh/Universal-Donwloader/releases/latest):
- `UniversalDownloader-android-arm64.apk` *(Recommended for modern Android phones)*
- `UniversalDownloader-android-universal.apk` *(Compatible with all Android devices)*

### 3. IzzyOnDroid & F-Droid
Standard Fastlane metadata is maintained in `fastlane/metadata/android/` for automated indexing by IzzyOnDroid and F-Droid client frontends (Droid-ify, Neo Store).

---

## 💻 Desktop Installation (Windows, Linux, macOS)

### Windows
- **Installer**: Download and run `UniversalDownloader-Setup-x64.msi` from [Releases](https://github.com/Antony-Gh/Universal-Donwloader/releases/latest).
- **Portable**: Download standalone `UniversalDownloader.exe`.

### Linux
Download `UniversalDownloader-linux-x64` or `UniversalDownloader-v4.0.0-linux-x64.tar.gz`:
```bash
tar -xzf UniversalDownloader-v4.0.0-linux-x64.tar.gz
chmod +x UniversalDownloader
./UniversalDownloader
```

### macOS
Download `UniversalDownloader-v4.0.0-macos-arm64.tar.gz` (Apple Silicon M1/M2/M3) or `UniversalDownloader-v4.0.0-macos-x64.tar.gz` (Intel).

---

## 🧩 Browser Companion Extension (Manifest V3)

A Chrome, Edge, and Brave companion extension is bundled in [`browser/extension/`](browser/extension) and packaged as `UniversalDownloader-v4.0.0-browser-extension.zip`.

### Features:
- **1-Click Download**: Click the extension icon to download the current video or extract audio.
- **Media Stream Sniffer**: Automatically detects embedded `.m3u8` (HLS), `.mpd` (DASH), and HTML5 `<video>` / `<audio>` streams on any webpage.
- **Context Menu**: Right-click any link or media element to download directly with Universal Downloader.
- **Native Host Communication**: Directly commands the local desktop app without requiring copy-pasting URLs.

### Manual Installation (Developer Mode):
1. Download `UniversalDownloader-v4.0.0-browser-extension.zip` from [Releases](https://github.com/Antony-Gh/Universal-Donwloader/releases/latest) and extract it.
2. In Chrome / Brave / Edge, open `chrome://extensions`.
3. Enable **Developer mode** (toggle in the top-right corner).
4. Click **Load unpacked** and select the extracted `browser/extension/` folder.
5. Register the Native Host in your terminal:
   ```bash
   python downloader.py --register-native-host
   ```

---

## 🛠️ CLI Usage & Advanced Commands

### 1. Basic Downloads
```bash
# Highest quality video + audio
python downloader.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Extract audio as 320kbps MP3 with embedded metadata & cover art
python downloader.py --audio-only --audio-format mp3 --audio-quality 320k --embed-metadata --embed-thumbnail "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# 10x Download acceleration via aria2c
python downloader.py --aria2 --aria2-connections 16 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 2. Local AI Whisper Transcription
```bash
# Transcribe speech into subtitles (.srt) and summary text (.txt) offline
python downloader.py --whisper --whisper-model base "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 3. Video-to-GIF, Clips & Frames
```bash
# Convert a segment of video into a high-framerate animated GIF
python downloader.py --to-gif --gif-start 00:00:10 --gif-duration 5 --gif-fps 15 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Extract a sub-clip without re-encoding
python downloader.py --make-clip 00:01:00-00:01:30 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Capture a full-resolution PNG video frame
python downloader.py --grab-frame 00:00:45 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 4. Smart Scheduling & Duplicate Prevention
```bash
# Automatically start batch download queue at 2:00 AM
python downloader.py --batch urls.txt --schedule 02:00 --pause-on-battery

# Skip downloading if the file or video ID already exists locally
python downloader.py --skip-duplicates "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 5. Send to Phone over LAN (LocalShare)
```bash
# Download and display a terminal QR code for instant phone download over Wi-Fi
python downloader.py --local-share "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 6. Music Tagging via MusicBrainz
```bash
# Query MusicBrainz & Cover Art Archive to tag an audio file
python downloader.py --tag-music "downloads/track.mp3"
```

### 7. Credits & Author Information
```bash
# Show project creator, GitHub profile, repository, and open-source acknowledgments
python downloader.py --credits
```

---

## 🏗️ Multi-OS Build & Packaging

Universal Media Downloader features a one-click Python build orchestrator (`build_and_publish.py`) that compiles and stages the entire suite:

```bash
# Build all OS binaries and package the browser extension locally
python build_and_publish.py --no-publish

# Compile and publish official release to GitHub
python build_and_publish.py -v 4.0.0
```

### Generated Distribution Assets in `releases/`:
- `UniversalDownloader.exe` *(Windows Standalone Portable)*
- `UniversalDownloader-Setup-x64.msi` *(Windows WiX Setup Installer)*
- `UniversalDownloader-v4.0.0-windows-x64.zip` *(Windows Complete Bundle)*
- `UniversalDownloader-linux-x64` *(Linux Standalone Executable)*
- `UniversalDownloader-v4.0.0-linux-x64.tar.gz` *(Linux Archive)*
- `UniversalDownloader-v4.0.0-macos-arm64.tar.gz` *(macOS Apple Silicon)*
- `UniversalDownloader-v4.0.0-macos-x64.tar.gz` *(macOS Intel)*
- `UniversalDownloader-android-arm64.apk` *(Android ARM64)*
- `UniversalDownloader-android-universal.apk` *(Android Universal)*
- `UniversalDownloader-v4.0.0-browser-extension.zip` *(Manifest V3 Companion Extension)*
- `SHA256SUMS.txt` *(Cryptographic Verification Checksums)*

---

## 🧪 Testing

The test suite covers CLI flags, engine pipelines, security boundaries, telemetry, and platform integrations:

```bash
# Run all Python unit & integration tests (183 tests)
pytest tests/ -v

# Run C# Core unit tests (17 tests)
dotnet run --project tests/UniversalDownloader.Core.Tests/UniversalDownloader.Core.Tests.csproj
```

---

## 👤 Author & Lead Developer

<table border="0">
  <tr>
    <td width="90" valign="top">
      <img src="https://github.com/Antony-Gh.png" width="80" height="80" style="border-radius: 50%;" alt="Anthony Gaius" />
    </td>
    <td>
      <strong>Anthony Gaius</strong> (<code>@Antony-Gh</code>)<br />
      <em>Creator, Architect & Lead Developer</em><br /><br />
      🌐 <strong>GitHub Profile</strong>: <a href="https://github.com/Antony-Gh">https://github.com/Antony-Gh</a><br />
      ⭐ <strong>Project Repository</strong>: <a href="https://github.com/Antony-Gh/Universal-Donwloader">Universal-Donwloader</a><br />
      ✉️ <strong>Contact & Support</strong>: <a href="mailto:knkmam05@gmail.com">knkmam05@gmail.com</a>
    </td>
  </tr>
</table>

### ❤️ Open-Source Acknowledgments
Universal Media Downloader is proudly built upon exceptional open-source technologies:
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**: World-class media extraction backend.
- **[FFmpeg](https://ffmpeg.org/)**: The premier multimedia processing framework.
- **[Avalonia UI](https://avaloniaui.net/)**: Cross-platform XAML .NET desktop GUI.
- **[Jetpack Compose](https://developer.android.com/jetpack/compose)**: Modern Android UI toolkit.
- **[aria2](https://github.com/aria2/aria2)**: High-speed multi-connection download utility.
- **[OpenAI Whisper](https://github.com/openai/whisper)**: Robust offline speech recognition.
- **[MusicBrainz](https://musicbrainz.org/)**: Open music encyclopedia and Cover Art Archive.

---

## ⚖️ Legal Notice

Universal Media Downloader is designed for educational, archiving, and research purposes on **publicly accessible content** that the user is authorized to download. It does not circumvent digital rights management (DRM), bypass paywalls, extract private credentials, or solve CAPTCHAs. Always respect copyright laws and platform terms of service.

---

## 📄 License

This project is open-source software licensed under the **[MIT License](LICENSE)**.
