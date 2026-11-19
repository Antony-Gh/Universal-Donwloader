# Universal Media Downloader — Android Edition (v4.0.0)

Native Android application built with **Kotlin**, **Jetpack Compose (Material 3)**, and **`youtubedl-android`** (embedded Python 3 + `yt-dlp` + `FFmpeg` runtime — zero external tools or Termux required).

## Features

- **Share Sheet Integration:** Tap **Share → Universal Downloader** directly inside YouTube, Instagram, TikTok, X/Twitter, or Chrome.
- **Auto Metadata & Thumbnail Preview:** Automatically loads title, uploader, duration badge, view count, and thumbnail on paste.
- **Stream Explorer:** Inspect every video/audio stream with non-overlapping resolution + container badges, codecs, and file sizes.
- **Interactive `"i"` Info Tooltips:** Tap any info icon beside Quality, Codec Preference, Fragments, Metadata, Cover Art, or Subtitles for clear explanations.
- **Background Foreground Service:** Downloads continue reliably with live progress notifications even when the screen is off.
- **One-Tap `yt-dlp` Updater:** Update the embedded `yt-dlp` extractor inside the app without reinstalling the APK.
- **History & Copyable Live Logs:** Play or share completed downloads directly from History, and filter/copy color-coded real-time engine logs.

## Building Locally

1. Open the `android/` folder in **Android Studio** (Ladybug or newer, JDK 17, Android SDK 35).
2. Run **Build → Build Bundle(s) / APK(s) → Build APK(s)**, or from terminal:

   ```bash
   cd android
   gradle assembleRelease
   ```

3. Output APKs are generated in `android/app/build/outputs/apk/release/`:
   - `app-arm64-v8a-release.apk` (recommended compact APK for modern Android phones)
   - `app-universal-release.apk` (compatible with all ABIs)

## Automated GitHub Releases

Every tagged release (`v*`) automatically builds `UniversalDownloader-android-arm64.apk` and `UniversalDownloader-android-universal.apk` via `.github/workflows/release.yml`.

## Installation & Automatic Updates (Obtainium / IzzyOnDroid)

Since Google Play restricts YouTube downloading applications under section 4.4 of the Developer Distribution Agreement, Universal Media Downloader is distributed directly through open-source channels:

### 1. Obtainium (Recommended for Seamless Updates)
[Obtainium](https://github.com/ImranR98/Obtainium) allows you to install and receive background update notifications directly from this GitHub repository.
- Open Obtainium on your Android device.
- Tap **Add App**.
- Paste URL: `https://github.com/Antony-Gh/Universal-Donwloader`
- Tap **Add** → Obtainium will automatically install and keep your app updated.

Or open this deep link directly on your phone:
- [`obtainium://add/https://github.com/Antony-Gh/Universal-Donwloader`](obtainium://add/https://github.com/Antony-Gh/Universal-Donwloader)

### 2. Direct APK Download
Download the latest signed APK directly from [GitHub Releases](https://github.com/Antony-Gh/Universal-Donwloader/releases/latest):
- `UniversalDownloader-android-arm64.apk` (Recommended for modern phones)
- `UniversalDownloader-android-universal.apk` (Compatible with all devices)

### 3. IzzyOnDroid & F-Droid Compatibility
This repository includes standard Fastlane metadata in `fastlane/metadata/android/` for automated indexing by IzzyOnDroid and F-Droid package managers (Droid-ify, Neo Store).
