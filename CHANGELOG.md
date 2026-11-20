# Changelog

All notable changes to **Universal Media Downloader** are documented in this file.

## [4.0.0] - 2026-11-20

### 🚀 Major Release: The All-in-One Media Archiving & Automation Suite

Universal Media Downloader v4.0.0 represents our most comprehensive release ever, bringing 15 major capabilities, full cross-platform feature parity across Desktop (Avalonia .NET 9), Android (Jetpack Compose), and CLI, local AI capabilities, and distribution enhancements.

### Added

- **Channel & Playlist Subscriptions (Desktop, Android, CLI)**:
  - Automatically follow and archive new uploads from YouTube channels, creators, and public playlists.
  - Desktop Avalonia UI: Dedicated Subscriptions tab with URL entry, audio/video presets, maximum download limits, sync progress bar, and card grid.
  - Android Jetpack Compose: Subscriptions screen with swipe-to-refresh, background sync, and direct uncompressed media playback.
  - Background CLI sync engine: `python downloader.py --subscriptions-sync --subscriptions-limit 5`.

- **Smart Scheduling, Wi-Fi Constraints & Battery Saver**:
  - Wall-clock download queue scheduling (`--schedule HH:MM`, e.g. `02:00` for off-peak downloads).
  - Battery Saver protection: Pauses or prevents starting heavy downloads when laptop or phone is running on battery power (`--pause-on-battery`).
  - Network constraints: Download only when connected to unmetered Wi-Fi connections (`--only-wifi`).

- **Desktop System Tray & Clipboard Monitoring**:
  - Avalonia desktop system tray icon with background minimize, active status tooltip, and one-click restore.
  - Background clipboard watcher on Desktop: Automatically detects copied media URLs and queues them without opening the app window.

- **aria2c Multi-Connection Acceleration**:
  - Integrated external downloader engine (`--aria2`, `--aria2-connections 16`) for up to 10x faster concurrent downloads on segmented streams.
  - Bundled automated downloader checking and configuration across CLI and Desktop.

- **Manifest V3 Browser Companion Extension (`browser/extension/`)**:
  - Chrome, Edge, and Brave extension featuring 1-click downloads, context-menu actions, and real-time page media stream sniffer (.m3u8, .mpd, HTML5 `<video>` / `<audio>`).
  - Communicates directly with the desktop app via Native Messaging host (`universal_downloader.native_host`).
  - Packaged as a clean zip archive (`UniversalDownloader-v4.0.0-browser-extension.zip`) attached to GitHub Releases.

- **Local AI Transcription with OpenAI Whisper (`--whisper`)**:
  - 100% offline, private speech-to-text transcription using local Whisper models (`tiny`, `base`, `small`, `medium`).
  - Generates synchronized subtitle files (.srt, .vtt) and plain text transcripts (.txt) without sending any audio to external cloud servers.

- **Video-to-GIF Maker, Clip Extractor & Frame Grabber**:
  - Create high-framerate, high-quality animated GIFs with dual-pass FFmpeg palette generation (`--to-gif --gif-fps 15 --gif-width 480`).
  - Extract exact video clips with millisecond precision without re-encoding (`--make-clip 00:01:00-00:01:30`).
  - High-resolution frame grabber saving uncompressed PNG snapshots (`--grab-frame 00:00:45`).

- **Music Tagging & Artwork via MusicBrainz & Cover Art Archive**:
  - Automatic acoustic fingerprinting and metadata lookup (`--tag-music`).
  - Enriches downloaded MP3/M4A/FLAC tracks with verified artist, album title, release year, track number, and high-resolution album artwork.

- **Send to Phone over LAN via QR Code (LocalShare)**:
  - LocalSend-style direct transfer from Desktop to Android or iOS over home Wi-Fi (`--local-share`).
  - Spawns a lightweight local HTTP streaming server with zero cloud relay, displaying an ASCII/graphical QR code in terminal and desktop app for one-click download on mobile.

- **Intelligent Duplicate Detection (`--skip-duplicates`)**:
  - Checks target directories before network requests, matching exact filenames, normalized titles, and video platform IDs to eliminate redundant bandwidth consumption.

- **Anonymous Crash Diagnostics into Neon Database**:
  - Opt-in error telemetry capturing sanitized exception stack traces directly into Neon PostgreSQL serverless database.
  - Automatically redacts usernames, local home directories, IP addresses, and URLs from crash reports.

- **Automated Daily Extractor Health CI Workflow (`.github/workflows/extractor-health.yml`)**:
  - Automated GitHub Actions scheduled workflow running daily test downloads across YouTube, TikTok, Reddit, and Vimeo to detect upstream website changes immediately.

- **Windows Authenticode Code Signing Automation**:
  - Automated PowerShell script (`scripts/sign_windows_binary.ps1`) supporting SignPath.io, Azure Trusted Signing, and PFX certificates.
  - Comprehensive guide in `docs/WINDOWS_CODE_SIGNING.md` on eliminating Windows Defender SmartScreen "Unknown Publisher" warnings.

- **Android Distribution via Obtainium & IzzyOnDroid**:
  - Direct repository update integration via Obtainium deep-link (`obtainium://add/https://github.com/Antony-Gh/Universal-Donwloader`).
  - Standard Fastlane metadata structure in `fastlane/metadata/android/` for IzzyOnDroid and F-Droid package managers.

- **In-App Privacy Transparency Dashboard & GDPR Data Controls**:
  - Dedicated Privacy tab in Avalonia Desktop app with clear privacy guarantees, anonymous device ID reset button, and one-click GDPR remote data wipe.
  - Hidden technical payload inspector by default (`IsVisible=false`, toggleable via `app_config.json` and user settings) to keep the interface friendly.

- **Dedicated Credits & Creator Tab**:
  - Added dedicated Credits & Creator tab honoring **Anthony Gaius** (`@Antony-Gh`) as Creator, Architect & Lead Developer.
  - Interactive profile links, repository shortcuts, issue tracker, email support (`knkmam05@gmail.com`), and open-source acknowledgments (yt-dlp, FFmpeg, Avalonia UI, Jetpack Compose, aria2c, Whisper).
  - CLI `--credits` / `--about` terminal card and JSON output support.

### Changed & Fixed

- **Desktop UI Overhaul (Queue & Subscriptions Tabs)**:
  - Converted Queue and Subscriptions control rows into dedicated responsive toolbar cards utilizing `WrapPanel`.
  - Widened `NumericUpDown` controls from 80px/85px to 105px with `FormatString="0"`, centered text alignment, and generous spacing to completely eliminate text and up/down arrow overlap.
  - Full Arabic (`عربي`) RTL layout compatibility preventing text clipping across all tabs.

### Verification

- **183 Python unit and integration tests passing** (`pytest tests/`).
- **17 C# Core unit tests passing** (`dotnet test tests/UniversalDownloader.Core.Tests`).
- Full cross-platform compilation clean with 0 errors across .NET 9 Avalonia and Android Release Kotlin.

## [3.6.0] - 2026-11-19

### Added

- **Remote Version Lifecycle & Deprecation Enforcement**:
  - Remote kill-switch and deprecation gate disabling client builds prior to **v3.6.0** (like Windows ending support for Win7).
  - Remotely configurable via Neon PostgreSQL `app_version_policy` table and `get_version_policy()` stored procedure with offline `version_policy.json` raw fallback.
  - Granular policy control: `min_supported_version`, `latest_version`, `blocked_versions` blacklist, `sunset_message`, `download_url`, and `enforcement_mode` (`block`, `warn`, `allow`).
  - Terminal CLI (`universal_downloader.version_policy`): Renders ASCII End-of-Life warning and safely halts execution before extractor initialization.
  - Maintainer / Debug bypass support via `--force-deprecated` CLI flag and configuration option.
  - Avalonia Desktop (.NET Core): Real-time policy checking with non-blocking async query, top-bar red End-of-Life banner, and download button disablement.
  - Android Jetpack Compose: `AppUpdateChecker.checkVersionPolicy()`, persistent UI state, and red End-of-Life banner with one-click direct upgrade button.

### Verification

- 142 Python unit and integration tests passing (`pytest tests/test_version_policy.py`).
- `.NET Core` (`UniversalDownloader.Core`), Avalonia Desktop (`UniversalDownloader.Avalonia`), and Android Release Kotlin (`compileReleaseKotlin`) all build cleanly with 0 errors.

## [3.4.0] - 2026-11-19

### Added

- **Anonymous Device & Platform Telemetry**:
  - Automatic hardware form-factor detection across **Desktop PC** vs. **Laptop** vs. **Android** vs. **macOS** vs. **Linux** (using Win32 `GetSystemPowerStatus`, Linux sysfs battery nodes, and Android build properties).
  - Cryptographically secure anonymous persistent installation UUIDv4 (`install_id`) stored locally in user configuration directory with zero personal identifiers.
  - Zero PII / Zero Activity Tracking: No IP addresses, usernames, downloaded URLs, media titles, or files are ever collected.
  - Full opt-out support via `--no-telemetry`, `UD_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`, or settings configuration.
- **Neon Serverless PostgreSQL Integration (`scripts/neon_schema.sql`)**:
  - Complete DDL schema and `record_device_heartbeat` stored function for atomic upserts over Neon's SQL-over-HTTPS endpoint (`POST /sql`).
  - Aggregated analytics views (`v_device_stats`, `v_device_breakdown`, `v_version_breakdown`) providing active device counts (last 7 days / 30 days) and form factor distributions.
  - Step-by-step 1-minute setup guide in `docs/TELEMETRY_SETUP.md`.
- **Maintainer Analytics CLI (`--analytics`, `--release-stats`)**:
  - Live GitHub Releases API download counters broken down by asset type (Windows Executables/MSI, Android APKs, Source archives).
  - Real-time Neon database device breakdown dashboard in console or structured `--json` / `--json-stream` output.
- **Desktop Avalonia & .NET Core Telemetry Integration**:
  - Added `PlatformUtils.DetectDeviceType()`, `GetOrCreateInstallId()`, and `SendTelemetryHeartbeatAsync()` to `UniversalDownloader.Core`.
  - Dispatches non-blocking async heartbeat on Avalonia app launch.
- **Android Jetpack Compose App Telemetry**:
  - Persistent `install_id` via `PreferencesStore` and non-blocking heartbeat dispatch on Android launch via `DownloaderRepository.sendDeviceHeartbeat()`.

- **Friend & Contributor Referral Identification**:
  - Automatically identify specific friends/beta-testers via executable filename pattern (e.g. `UniversalDownloader_ahmed.exe` -> `friend_tag = "ahmed"`), CLI flags (`--friend <name>`, `--ref <tag>`), environment variable (`UD_FRIEND_TAG`), or `config.json`.
  - Added `v_friend_installs` view and dedicated **Identified Friends & Beta Testers** section in maintainer `--analytics` CLI dashboard.
- **Extended Hardware & Regional Demographics**:
  - Automatic detection of system locale/language, system timezone, CPU cores, CPU architecture (`x86_64`, `arm64`), total physical RAM in GB, primary screen resolution, and network connection status with zero elevated permissions.

### Verification

- 134 Python unit and integration tests passing (`pytest`).
- `.NET Core` (`UniversalDownloader.Core`), Avalonia Desktop (`UniversalDownloader.Avalonia`), and Android Release Kotlin (`compileReleaseKotlin`) all build cleanly with 0 errors.

## [3.3.0] - 2026-11-19

### Added

- **YouTube Canonical URL Parsing**: Strict 11-character video ID extraction across `youtu.be`, `embed`, `live`, `shorts`, and `watch` URLs while stripping tracking params (`si`, `feature`, `fbclid`) and preserving playlist `list=` context.
- **YouTube Text Search (`--search`) & Live Autosuggest (`--suggest`)**: Search by song/artist name directly from CLI, Avalonia Desktop UI, and Android Jetpack Compose UI with debounced live autosuggestions.
- **Staged Progress Lifecycle**: Granular progress stages (`preparing`, `checking`, `extracting`, `downloading`, `converting`, `completed`) across Python JSON stream, `.NET Core`, and Android UI.
- **Deep-Link Format Shortcuts**: Support `#ID/mp3`, `#ID/mp4`, `url#mp3`, and `url#audio` hashes to automatically select audio/video mode.
- **Smart Subfolder Routing & Filename Sanitization (`--organize`, `--clean-filenames`)**: Organize downloads by `none`, `platform`, `uploader`, or `date` and strip clickbait tags (`[Official Video]`, `(Lyrics)`, `4K`) and emojis.
- **Browser Native Messaging Host (CoApp) & Userscript**: Standard Chrome/Edge/Firefox stdio Native Messaging host (`--native-host`, `--register-native-host`) plus `browser/universal_downloader.user.js` for 1-click Video/MP3 downloads.
- **Generic Webpage Media Sniffer (`--sniff`)**: Parse arbitrary HTML pages for `<video>`, `<audio>`, `<source>`, OpenGraph, Twitter cards, JSON-LD `contentUrl`, and inline HLS (`.m3u8`) / DASH (`.mpd`) streams.
- **Direct Local Media Converter (`--convert`, `--convert-audio`, `--convert-video`)**: Convert local files or losslessly remux containers directly via bundled FFmpeg.
- **Live Stream Recording Duration Cap (`--record-duration`, `--live-from-start`)**: Record live broadcasts with clean FFmpeg `-t` cutoff and container finalization.
- **MIT License**: Added root `LICENSE` file and updated package metadata.

### Verification

- 109 Python unit/integration tests passing (`pytest`).
- `.NET Core` (`UniversalDownloader.Core`), Avalonia Desktop (`UniversalDownloader.Avalonia`), and Android Release Kotlin (`compileReleaseKotlin`) all build cleanly with 0 errors.
