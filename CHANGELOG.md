# Changelog

All notable changes to **Universal Media Downloader** are documented in this file.

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
