# Changelog

All notable changes to **Universal Media Downloader** are documented in this file.

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

### Verification

- 132 Python unit and integration tests passing (`pytest`).
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
