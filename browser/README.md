# Universal Media Downloader — Browser Companion

Universal Media Downloader provides browser integration options:
1. **Manifest V3 Web Extension** (Chrome, Edge, Brave, Opera, Firefox)
2. **Userscript** (Tampermonkey, Violentmonkey)

---

## 1. Browser Extension (Manifest V3)

The extension provides:
- **Right-Click Context Menu**: Right-click any link, video, audio, or webpage background and select **"Download Video (MP4) with Universal Downloader"** or **"Extract Audio (MP3) with Universal Downloader"**.
- **Page Media Sniffer Toolbar Popup**: Click the toolbar icon to automatically discover media embedded in the page, including:
  - HTML5 `<video>` and `<audio>` stream sources
  - HLS streaming playlists (`.m3u8`)
  - DASH streaming manifests (`.mpd`)
  - OpenGraph / Twitter video metadata
- **Seamless Desktop App Handoff**: Dispatches URLs directly to Universal Media Downloader via Native Messaging (`com.universaldownloader.coapp`) with automatic fallback to the `downloader://` custom URI scheme.

### Installation Instructions

#### Google Chrome / Microsoft Edge / Brave / Opera
1. Open your browser's extension manager:
   - Chrome / Brave: `chrome://extensions`
   - Edge: `edge://extensions`
   - Opera: `opera://extensions`
2. Enable **Developer mode** (toggle in top-right or sidebar).
3. Click **Load unpacked** (or "Load unpacked extension").
4. Select the `browser/extension` directory inside this repository.
5. The **Universal Media Downloader Companion** icon will appear in your extensions toolbar. Pin it for quick access.

#### Mozilla Firefox
1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on...**.
3. Navigate to `browser/extension/manifest.json` and select it.

---

## 2. Userscript (Tampermonkey / Violentmonkey)

For users who prefer a single lightweight userscript:
1. Install [Tampermonkey](https://www.tampermonkey.net/) or [Violentmonkey](https://violentmonkey.github.io/).
2. Open `browser/universal_downloader.user.js` in your browser or copy-paste it into a new script in your userscript manager.
3. A floating **"⬇ Download"** button will appear on supported media pages (YouTube, TikTok, Twitter/X, Instagram, Facebook, Reddit, Vimeo, SoundCloud).
