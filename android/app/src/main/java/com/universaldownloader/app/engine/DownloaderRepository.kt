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
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.Locale

class DownloaderRepository(private val appContext: Context) {

    private val ignoredLogPatterns = listOf(
        "SSAP (server-side ads) experiment",
        "SABR-only streaming experiment",
        "Missing required Visitor Data",
        "android client https formats require a GVS PO Token",
        "No GVS PO Token provided",
        "This client will be deprioritized",
        "Some web client https formats have been skipped",
        "Some ios client https formats have been skipped",
        "formats have been skipped as they are missing a url",
        "unavailable video is hidden",
        "unavailable videos are hidden",
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
                addOption("--extractor-args", "youtube:player_client=android_vr,tv_embedded,web;formats=missing_pot")
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
                addOption("--extractor-args", "youtube:player_client=android_vr,tv_embedded,web;formats=missing_pot")
                addOption("--retries", "3")
                addOption("--fragment-retries", "3")
                addOption("--newline")
                if (url.contains("list=", ignoreCase = true) || url.contains("/playlist", ignoreCase = true)) {
                    addOption("--ignore-errors")
                }

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
                val startTrim = options.startTime.trim()
                val endTrim = options.endTime.trim()
                if (startTrim.isNotEmpty() || endTrim.isNotEmpty()) {
                    val startPart = startTrim.ifEmpty { "0:00" }
                    val endPart = endTrim.ifEmpty { "inf" }
                    addOption("--download-sections", "*$startPart-$endPart")
                    addOption("--force-keyframes-at-cuts")
                }
                val plItems = options.playlistItems.trim()
                if (plItems.isNotEmpty()) {
                    addOption("--playlist-items", plItems)
                }
                if (options.sponsorBlockEnabled) {
                    addOption("--sponsorblock-remove", "sponsor,intro,outro,selfpromo")
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

    /**
     * Resolve shorthand inputs (e.g. instagram:user, facebook:user, tiktok:user, x:user, youtube:user)
     * or standard profile URLs into a normalized HTTPS profile URL.
     */
    fun resolveProfileUrl(rawInput: String): String {
        val cleaned = rawInput.trim().trim('"', '\'')
        if (cleaned.isBlank()) throw IllegalArgumentException("Enter a profile URL or platform:username.")

        if (cleaned.contains("://") || cleaned.startsWith("www.") || cleaned.substringBefore('/').contains('.')) {
            return normalizeUrl(cleaned)
        }

        if (cleaned.contains(':')) {
            val prefix = cleaned.substringBefore(':').trim().lowercase(Locale.US)
            val user = cleaned.substringAfter(':').trim().trimStart('@')
            if (user.isNotBlank()) {
                return when (prefix) {
                    "facebook", "fb" -> "https://www.facebook.com/$user/"
                    "instagram", "ig" -> "https://www.instagram.com/$user/"
                    "tiktok" -> "https://www.tiktok.com/@$user"
                    "twitter", "x" -> "https://x.com/$user"
                    "threads" -> "https://www.threads.net/@$user"
                    "youtube", "yt" -> "https://www.youtube.com/@$user"
                    "reddit" -> "https://www.reddit.com/user/$user"
                    "twitch" -> "https://www.twitch.tv/$user"
                    "soundcloud" -> "https://soundcloud.com/$user"
                    "bluesky", "bsky" -> "https://bsky.app/profile/$user"
                    else -> "https://$prefix.com/$user/"
                }
            }
        }

        throw IllegalArgumentException(
            "Use a full profile URL or platform:username (e.g. instagram:user, facebook:user, tiktok:user, x:user)."
        )
    }

    private fun buildCookieHeaderForHost(cookiesFilePath: String?, host: String): String? {
        if (cookiesFilePath.isNullOrBlank()) return null
        val file = File(cookiesFilePath)
        if (!file.exists()) return null

        val targetHost = host.lowercase(Locale.US)
        val pairs = mutableListOf<String>()
        file.forEachLine { rawLine ->
            val line = rawLine.trim()
            if (line.isEmpty() || (line.startsWith("#") && !line.startsWith("#HttpOnly_"))) return@forEachLine
            val normalizedLine = line.removePrefix("#HttpOnly_")
            val cols = normalizedLine.split('\t')
            if (cols.size < 7) return@forEachLine
            val domain = cols[0].trim().lowercase(Locale.US).trimStart('.')
            val name = cols[5].trim()
            val value = cols[6].trim()
            if (domain.isNotEmpty() && name.isNotEmpty() && (targetHost == domain || targetHost.endsWith(".$domain"))) {
                pairs.add("$name=$value")
            }
        }
        return pairs.takeIf { it.isNotEmpty() }?.joinToString("; ")
    }

    private fun isGenericSiteLogo(url: String): Boolean {
        val lowered = url.lowercase(Locale.US)
        return listOf(
            "/rsrc.php/",
            "static.xx.fbcdn.net/rsrc",
            "static.cdninstagram.com/rsrc",
            "instagram.com/static/images/ico",
            "abs.twimg.com/responsive-web/client-web/icon",
            "favicon.ico",
            "apple-touch-icon",
            "fb_icon_325x325.png",
        ).any { lowered.contains(it) }
    }

    private fun extractMetaImageUrl(htmlText: String): String? {
        val patterns = listOf(
            Regex("""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)""", RegexOption.IGNORE_CASE),
            Regex("""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image""", RegexOption.IGNORE_CASE),
            Regex("""<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)""", RegexOption.IGNORE_CASE),
            Regex("""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']twitter:image""", RegexOption.IGNORE_CASE),
        )
        for (regex in patterns) {
            val match = regex.find(htmlText)
            if (match != null) {
                return match.groupValues[1].replace("&amp;", "&")
            }
        }
        return null
    }

    /**
     * Download a public or cookie-authorized profile picture into Downloads/UniversalDownloader/profile_pictures/.
     * Strictly respects platform authorization via the user's own optional cookies.txt session.
     */
    suspend fun downloadProfilePicture(
        profileInput: String,
        cookiesFilePath: String? = null,
        onLog: (String) -> Unit,
    ): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val profileUrl = resolveProfileUrl(profileInput)
            val host = runCatching { URI(profileUrl).host.orEmpty() }.getOrDefault("")
            val hasCookies = !cookiesFilePath.isNullOrBlank() && File(cookiesFilePath).exists()
            onLog(
                if (hasCookies) "[Profile] Resolving profile picture using configured cookies: $profileUrl"
                else "[Profile] Resolving public profile picture: $profileUrl"
            )

            val candidates = mutableListOf<String>()

            // 1. Try yt-dlp flat info (uses user's cookies if configured)
            runCatching {
                val req = YoutubeDLRequest(profileUrl).apply {
                    addOption("--dump-single-json")
                    addOption("--skip-download")
                    addOption("--flat-playlist")
                    if (hasCookies) {
                        addOption("--cookies", cookiesFilePath!!)
                    }
                }
                val resp = YoutubeDL.getInstance().execute(req, null)
                val raw = resp.out.trim()
                val startIdx = raw.indexOf('{')
                if (startIdx >= 0) {
                    val json = JSONObject(raw.substring(startIdx))
                    for (key in listOf("avatar", "channel_thumbnail", "uploader_thumbnail", "thumbnail")) {
                        val v = json.optString(key, "")
                        if (v.startsWith("http")) candidates.add(v)
                    }
                    val thumbs = json.optJSONArray("thumbnails")
                    if (thumbs != null) {
                        for (i in thumbs.length() - 1 downTo 0) {
                            val u = thumbs.optJSONObject(i)?.optString("url", "") ?: ""
                            if (u.startsWith("http")) candidates.add(u)
                        }
                    }
                }
            }

            // 2. Standard profile HTML OpenGraph metadata (with user's session cookies if available)
            runCatching {
                val conn = (URL(profileUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    instanceFollowRedirects = true
                    connectTimeout = 15_000
                    readTimeout = 20_000
                    setRequestProperty(
                        "User-Agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    )
                    buildCookieHeaderForHost(cookiesFilePath, host)?.let {
                        setRequestProperty("Cookie", it)
                    }
                }
                try {
                    if (conn.responseCode in 200..299) {
                        val html = conn.inputStream.bufferedReader().use { it.readText() }
                        extractMetaImageUrl(html)?.let { img ->
                            val absUrl = runCatching { URI(profileUrl).resolve(img).toString() }.getOrDefault(img)
                            if (absUrl.startsWith("http")) candidates.add(absUrl)
                        }
                    }
                } finally {
                    conn.disconnect()
                }
            }

            val validCandidates = candidates.distinct().filterNot { isGenericSiteLogo(it) }
            if (validCandidates.isEmpty()) {
                throw RuntimeException(
                    if (hasCookies) {
                        "No profile picture could be resolved with your current session cookies. " +
                            "The account may be private/locked without permission, or cookies may need refreshing."
                    } else {
                        "No public profile picture found. For profiles your account is authorized to view, sign in via Web Login or import cookies.txt."
                    }
                )
            }

            val outDir = File(getOutputDirectory(audioOnly = false), "profile_pictures").apply { mkdirs() }
            val safeName = (URI(profileUrl).path.trim('/').split('/').lastOrNull()?.trimStart('@') ?: "profile")
                .replace(Regex("[^A-Za-z0-9._-]"), "_")
                .ifBlank { "profile" }

            var lastError: Exception? = null
            for (imageUrl in validCandidates) {
                try {
                    val imgHost = runCatching { URI(imageUrl).host.orEmpty() }.getOrDefault("")
                    val ext = URI(imageUrl).path.substringAfterLast('.', "").lowercase(Locale.US)
                        .takeIf { it in setOf("jpg", "jpeg", "png", "webp", "gif") } ?: "jpg"
                    val dest = File(outDir, "${safeName}_${System.currentTimeMillis()}.$ext")
                    val conn = (URL(imageUrl).openConnection() as HttpURLConnection).apply {
                        requestMethod = "GET"
                        instanceFollowRedirects = true
                        connectTimeout = 15_000
                        readTimeout = 20_000
                        setRequestProperty(
                            "User-Agent",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        )
                        buildCookieHeaderForHost(cookiesFilePath, imgHost)?.let {
                            setRequestProperty("Cookie", it)
                        }
                    }
                    try {
                        if (conn.responseCode !in 200..299) {
                            throw RuntimeException("Image download returned HTTP ${conn.responseCode}")
                        }
                        conn.inputStream.use { input ->
                            dest.outputStream().use { output -> input.copyTo(output) }
                        }
                    } finally {
                        conn.disconnect()
                    }
                    MediaScannerConnection.scanFile(appContext, arrayOf(dest.absolutePath), null, null)
                    onLog("[Complete] Profile picture saved: ${dest.name}")
                    return@runCatching dest
                } catch (ex: Exception) {
                    lastError = ex
                }
            }
            throw lastError ?: RuntimeException("Profile picture could not be downloaded.")
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
