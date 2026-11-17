package com.universaldownloader.app.engine

import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Environment
import com.universaldownloader.app.model.CodecOption
import com.universaldownloader.app.model.DownloadOptions
import com.universaldownloader.app.model.MediaMetadata
import com.universaldownloader.app.model.QualityOption
import com.universaldownloader.app.model.StreamFormat
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.Locale

class DownloaderRepository(private val appContext: Context) {

    private val ignoredLogPatterns = listOf(
        "SSAP (server-side ads) experiment",
        "Missing required Visitor Data",
        "android client https formats require a GVS PO Token",
        "No GVS PO Token provided",
        "This client will be deprioritized",
        "Some web client https formats have been skipped",
        "formats have been skipped as they are missing a url",
    )

    suspend fun initEngine(): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            YoutubeDL.getInstance().init(appContext)
            FFmpeg.getInstance().init(appContext)
        }
    }

    suspend fun updateEngine(): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val status = YoutubeDL.getInstance().updateYoutubeDL(
                appContext,
                YoutubeDL.UpdateChannel.STABLE,
            )
            when (status) {
                YoutubeDL.UpdateStatus.DONE -> "yt-dlp engine updated to latest release!"
                YoutubeDL.UpdateStatus.ALREADY_UP_TO_DATE -> "yt-dlp engine is already up to date."
                else -> "Update check completed."
            }
        }
    }

    fun normalizeUrl(rawInput: String): String {
        val trimmed = rawInput.trim().trim('"', '\'')
        if (trimmed.isEmpty()) return ""

        // Extract first URL if user shared text containing a title + link (e.g. from YouTube/TikTok Share Sheet)
        val urlRegex = Regex("""https?://[^\s"'<>]+""")
        val extracted = urlRegex.find(trimmed)?.value ?: trimmed

        return try {
            val uri = Uri.parse(extracted)
            val host = (uri.host ?: "").lowercase(Locale.US)
            val path = uri.path ?: ""

            // Strip noisy tracking params on Instagram & TikTok media URLs
            val isInstagramMedia = host.contains("instagram.com") &&
                Regex("""/(reel|reels|p|tv)/[^/]+""", RegexOption.IGNORE_CASE).containsMatchIn(path)
            val isTikTokVideo = host.contains("tiktok.com") &&
                Regex("""/video/\d+""", RegexOption.IGNORE_CASE).containsMatchIn(path)

            if (isInstagramMedia || isTikTokVideo) {
                val cleanPath = if (isInstagramMedia && !path.endsWith("/")) "$path/" else path
                "${uri.scheme ?: "https"}://${uri.host}$cleanPath"
            } else {
                extracted
            }
        } catch (_: Exception) {
            extracted
        }
    }

    fun detectPlatformLabel(url: String): String {
        val host = try {
            (Uri.parse(url).host ?: "").lowercase(Locale.US).removePrefix("www.").removePrefix("m.")
        } catch (_: Exception) {
            ""
        }
        return when {
            host.contains("youtube") || host.contains("youtu.be") -> "YOUTUBE"
            host.contains("instagram") -> "INSTAGRAM"
            host.contains("tiktok") -> "TIKTOK"
            host.contains("facebook") || host.contains("fb.watch") -> "FACEBOOK"
            host.contains("twitter") || host.contains("x.com") -> "X / TWITTER"
            host.contains("soundcloud") -> "SOUNDCLOUD"
            host.contains("vimeo") -> "VIMEO"
            host.contains("reddit") || host.contains("redd.it") -> "REDDIT"
            host.contains("twitch") -> "TWITCH"
            host.contains("pinterest") || host.contains("pin.it") -> "PINTEREST"
            host.contains("threads") -> "THREADS"
            else -> "MEDIA"
        }
    }

    suspend fun fetchMetadataAndFormats(
        rawUrl: String,
        cookiesFilePath: String? = null,
    ): Result<MediaMetadata> = withContext(Dispatchers.IO) {
        runCatching {
            val url = normalizeUrl(rawUrl)
            val request = YoutubeDLRequest(url).apply {
                addOption("--dump-single-json")
                addOption("--no-playlist")
                addOption("--no-warnings")
                addOption("--extractor-args", "youtube:player_client=ios,android_vr,web;formats=missing_pot")
                addOption("--socket-timeout", "25")
                if (!cookiesFilePath.isNullOrBlank() && File(cookiesFilePath).exists()) {
                    addOption("--cookies", cookiesFilePath)
                }
            }

            val response = YoutubeDL.getInstance().execute(request)
            val rawOut = response.out.trim()
            val jsonStart = rawOut.indexOf('{')
            if (jsonStart < 0) {
                throw RuntimeException(response.err.ifBlank { "No metadata returned by extractor." })
            }
            val root = JSONObject(rawOut.substring(jsonStart))

            val parsedFormats = mutableListOf<StreamFormat>()
            val formatsArr = root.optJSONArray("formats")
            if (formatsArr != null) {
                for (i in 0 until formatsArr.length()) {
                    val fmt = formatsArr.optJSONObject(i) ?: continue
                    val id = fmt.optString("format_id", "")
                    if (id.isBlank()) continue
                    val ext = fmt.optString("ext", "mp4").ifBlank { "mp4" }
                    val vcodec = fmt.optString("vcodec", "").takeIf { it.isNotBlank() && it != "null" }
                    val acodec = fmt.optString("acodec", "").takeIf { it.isNotBlank() && it != "null" }
                    if (ext == "mhtml" || vcodec == "images") continue

                    val width = fmt.optInt("width", 0).takeIf { it > 0 }
                    val height = fmt.optInt("height", 0).takeIf { it > 0 }
                    val fps = fmt.optDouble("fps", 0.0).takeIf { !it.isNaN() && it > 0.0 }?.toInt()
                    val filesize = fmt.optLong("filesize", 0L).takeIf { it > 0L }
                        ?: fmt.optLong("filesize_approx", 0L).takeIf { it > 0L }
                    val note = fmt.optString("format_note", "").takeIf { it.isNotBlank() && it != "null" }

                    parsedFormats.add(
                        StreamFormat(
                            formatId = id,
                            extension = ext,
                            width = width,
                            height = height,
                            fps = fps,
                            vcodec = vcodec,
                            acodec = acodec,
                            formatNote = note,
                            filesizeBytes = filesize,
                        )
                    )
                }
            }

            val sortedFormats = parsedFormats.sortedWith(
                compareByDescending<StreamFormat> { it.height ?: 0 }
                    .thenByDescending { it.fps ?: 0 }
                    .thenByDescending { it.filesizeBytes ?: 0L }
            )

            val title = root.optString("title", "").takeIf { it.isNotBlank() && it != "null" } ?: "Unknown Title"
            val uploader = root.optString("uploader", "").takeIf { it.isNotBlank() && it != "null" }
                ?: root.optString("channel", "").takeIf { it.isNotBlank() && it != "null" }
                ?: root.optString("creator", "").takeIf { it.isNotBlank() && it != "null" }
                ?: "Unknown Creator"
            val duration = root.optDouble("duration", 0.0).takeIf { !it.isNaN() && it > 0.0 }?.toLong()
            val thumbnail = root.optString("thumbnail", "").takeIf { it.isNotBlank() && it != "null" }
            val viewCount = root.optLong("view_count", 0L).takeIf { it > 0L }

            MediaMetadata(
                url = url,
                platform = detectPlatformLabel(url),
                title = title,
                uploader = uploader,
                durationSeconds = duration,
                thumbnailUrl = thumbnail,
                viewCount = viewCount,
                formats = sortedFormats,
            )
        }
    }

    fun getOutputDirectory(audioOnly: Boolean): File {
        val publicDir = Environment.getExternalStoragePublicDirectory(
            if (audioOnly) Environment.DIRECTORY_MUSIC else Environment.DIRECTORY_DOWNLOADS
        )
        val appDir = File(publicDir, "UniversalDownloader")
        if (!appDir.exists()) {
            appDir.mkdirs()
        }
        if (appDir.exists() && appDir.canWrite()) {
            return appDir
        }
        val fallback = File(
            appContext.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: appContext.filesDir,
            "UniversalDownloader",
        )
        fallback.mkdirs()
        return fallback
    }

    suspend fun download(
        rawUrl: String,
        options: DownloadOptions,
        processId: String,
        onProgress: (percent: Float, etaSeconds: Long, line: String) -> Unit,
        onLog: (String) -> Unit,
    ): Result<File?> = withContext(Dispatchers.IO) {
        runCatching {
            val url = normalizeUrl(rawUrl)
            val isAudioOnly = options.quality == QualityOption.AUDIO_MP3 && options.explicitFormatId == null
            val outDir = getOutputDirectory(isAudioOnly)
            val beforeFiles = outDir.listFiles()?.map { it.absolutePath }?.toSet() ?: emptySet()

            val request = YoutubeDLRequest(url).apply {
                addOption("-o", "${outDir.absolutePath}/%(title).120B [%(id)s].%(ext)s")
                addOption("--concurrent-fragments", options.concurrentFragments.coerceIn(1, 16).toString())
                addOption("--extractor-args", "youtube:player_client=ios,android_vr,web;formats=missing_pot")
                addOption("--retries", "3")
                addOption("--fragment-retries", "3")
                addOption("--newline")

                if (options.explicitFormatId != null) {
                    addOption("-f", "${options.explicitFormatId}+bestaudio/${options.explicitFormatId}/best")
                    addOption("--merge-output-format", "mp4")
                } else if (isAudioOnly) {
                    addOption("-x")
                    addOption("--audio-format", "mp3")
                    addOption("--audio-quality", "320K")
                } else {
                    addOption("-f", buildFormatSelector(options.quality, options.codec))
                    addOption("--merge-output-format", "mp4")
                }

                if (options.embedMetadata) {
                    addOption("--embed-metadata")
                }
                if (options.embedThumbnail) {
                    addOption("--embed-thumbnail")
                }
                if (options.embedSubs && !isAudioOnly) {
                    addOption("--embed-subs")
                    addOption("--sub-langs", "en.*,ar.*")
                }
                if (options.writeThumbnail) {
                    addOption("--write-thumbnail")
                }
                val cookiesPath = options.cookiesFilePath
                if (!cookiesPath.isNullOrBlank() && File(cookiesPath).exists()) {
                    addOption("--cookies", cookiesPath)
                }
            }

            onLog("Starting download to: ${outDir.absolutePath}")

            val response = YoutubeDL.getInstance().execute(request, processId) { progress, etaInSeconds, line ->
                val cleanLine = line.trim()
                if (cleanLine.isNotEmpty() && !isIgnoredLine(cleanLine)) {
                    // Only log non-spam status lines; progress numbers update the progress bar smoothly
                    if (!cleanLine.startsWith("[download]") || cleanLine.contains("Destination:") || cleanLine.contains("100%")) {
                        onLog(cleanLine)
                    }
                }
                onProgress(progress.coerceIn(0f, 100f), etaInSeconds, cleanLine)
            }

            if (response.exitCode != 0) {
                val errDetail = response.err.ifBlank { "Download exited with code ${response.exitCode}" }
                throw RuntimeException(errDetail.trim())
            }

            val createdFile = outDir.listFiles()
                ?.filter { it.isFile && it.absolutePath !in beforeFiles && !it.name.endsWith(".part") }
                ?.maxByOrNull { it.lastModified() }
                ?: outDir.listFiles()
                    ?.filter { it.isFile && !it.name.endsWith(".part") }
                    ?.maxByOrNull { it.lastModified() }

            if (createdFile != null) {
                MediaScannerConnection.scanFile(
                    appContext,
                    arrayOf(createdFile.absolutePath),
                    null,
                    null,
                )
                onLog("[Complete] Saved: ${createdFile.name}")
            } else {
                onLog("[Complete] Download finished in ${outDir.absolutePath}")
            }

            createdFile
        }
    }

    fun cancelDownload(processId: String) {
        try {
            YoutubeDL.getInstance().destroyProcessById(processId)
        } catch (_: Exception) {
        }
    }

    private fun isIgnoredLine(line: String): Boolean {
        return ignoredLogPatterns.any { line.contains(it, ignoreCase = true) }
    }

    private fun buildFormatSelector(quality: QualityOption, codec: CodecOption): String {
        val heightLimit = when (quality) {
            QualityOption.P1080 -> "[height<=1080]"
            QualityOption.P720 -> "[height<=720]"
            QualityOption.P480 -> "[height<=480]"
            else -> ""
        }
        val codecFilter = when (codec) {
            CodecOption.H264 -> "[vcodec^=avc1]"
            CodecOption.VP9 -> "[vcodec^=vp9]"
            CodecOption.AV1 -> "[vcodec^=av01]"
            CodecOption.AUTO -> ""
        }
        return if (codecFilter.isNotEmpty()) {
            "bestvideo$heightLimit$codecFilter+bestaudio/bestvideo$heightLimit+bestaudio/best$heightLimit/best"
        } else {
            "bestvideo$heightLimit+bestaudio/best$heightLimit/best"
        }
    }
}
