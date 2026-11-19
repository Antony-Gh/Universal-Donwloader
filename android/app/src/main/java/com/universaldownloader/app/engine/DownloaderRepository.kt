package com.universaldownloader.app.engine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
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
import org.json.JSONArray
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
        "Your yt-dlp version",
        "is older than 90 days",
        "yt-dlp-update",
        "yt-dlp -U",
        "yt-dlp-U",
        "To suppress this warning",
        "The extractor is attempting impersonation",
        "no impersonate target is available",
    )

    fun getEngineVersion(): String? {
        return try {
            YoutubeDL.getInstance().version(appContext)
        } catch (_: Exception) {
            null
        }
    }

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
            val currentVersion = getEngineVersion() ?: ""
            when (status) {
                YoutubeDL.UpdateStatus.DONE -> "yt-dlp engine updated to latest release ($currentVersion)!"
                YoutubeDL.UpdateStatus.ALREADY_UP_TO_DATE -> "yt-dlp engine is up to date ($currentVersion)."
                else -> "Update check completed ($currentVersion)."
            }
        }
    }

    companion object {
        /** youtu.be/ID, /embed/ID, /live/ID, /shorts/ID, /v/ID and ?v=ID / &v=ID (11-char IDs). */
        private val YOUTUBE_ID_REGEX = Regex(
            """(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:embed/|live/|shorts/|v/)|[?&]v=)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])""",
            RegexOption.IGNORE_CASE,
        )
        private val DEEP_LINK_HASH_REGEX = Regex(
            """^#?([A-Za-z0-9_-]{11})(?:/([A-Za-z0-9]+))?$"""
        )
        private val KNOWN_FORMAT_HINTS = setOf(
            "mp3", "mp4", "audio", "video", "m4a", "flac", "opus", "wav", "aac", "best"
        )

        /** Returns the 11-character YouTube video ID found in [value], or null. */
        fun extractYoutubeVideoId(value: String): String? =
            YOUTUBE_ID_REGEX.find(value.trim())?.groupValues?.get(1)

        /** Parse direct deep-link format shortcuts (#ID/format, url#format, etc). */
        fun extractFormatHint(rawInput: String): Pair<String, String?> {
            val trimmed = rawInput.trim().trim('"', '\'')
            if (trimmed.isEmpty()) return Pair("", null)

            val m = DEEP_LINK_HASH_REGEX.matchEntire(trimmed)
            if (m != null) {
                val vid = m.groupValues[1]
                val fmt = m.groupValues.getOrNull(2)?.takeIf { it.isNotEmpty() }?.lowercase(Locale.US)
                return Pair("https://www.youtube.com/watch?v=$vid", fmt)
            }

            if (trimmed.contains('#')) {
                val parts = trimmed.split('#', limit = 2)
                val base = parts[0].trim()
                val fragment = parts[1].trim().lowercase(Locale.US)

                val subM = DEEP_LINK_HASH_REGEX.matchEntire(fragment)
                if (subM != null) {
                    val vid = subM.groupValues[1]
                    val fmt = subM.groupValues.getOrNull(2)?.takeIf { it.isNotEmpty() }?.lowercase(Locale.US)
                    return Pair("https://www.youtube.com/watch?v=$vid", fmt)
                }

                if (fragment in KNOWN_FORMAT_HINTS) {
                    val resolvedBase = if (base.matches(Regex("^[A-Za-z0-9_-]{11}$"))) {
                        "https://www.youtube.com/watch?v=$base"
                    } else {
                        base
                    }
                    return Pair(resolvedBase, fragment)
                }
            }

            return Pair(trimmed, null)
        }
    }

    fun normalizeUrl(rawInput: String): String {
        val (cleanedHint, _) = extractFormatHint(rawInput)
        val trimmed = (if (cleanedHint.isNotEmpty()) cleanedHint else rawInput).trim().trim('"', '\'')
        if (trimmed.isEmpty()) return ""

        // Extract first URL if user shared text containing a title + link (e.g. from YouTube/TikTok Share Sheet)
        val urlRegex = Regex("""https?://[^\s"'<>]+""")
        val extracted = urlRegex.find(trimmed)?.value ?: trimmed

        return try {
            val uri = Uri.parse(extracted)
            val host = (uri.host ?: "").lowercase(Locale.US)
            val path = uri.path ?: ""

            // Canonicalise single-video YouTube links (drops si=/feature= tracking); keep playlists intact
            val isYoutubeHost = host.contains("youtube.com") || host.contains("youtu.be") ||
                host.contains("youtube-nocookie.com")
            if (isYoutubeHost &&
                uri.getQueryParameter("list").isNullOrBlank() &&
                !path.lowercase(Locale.US).contains("/playlist")
            ) {
                extractYoutubeVideoId(extracted)?.let { return "https://www.youtube.com/watch?v=$it" }
            }

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

    fun isValidUrl(rawUrl: String): Boolean {
        val trimmed = rawUrl.trim().trim('"', '\'')
        if (trimmed.length < 4) return false
        if (trimmed.contains(':') && !trimmed.contains("://")) {
            val parts = trimmed.split(':', limit = 2)
            val platform = parts[0].trim().lowercase(Locale.US)
            val identifier = parts[1].trim()
            if (platform in setOf("instagram", "facebook", "tiktok", "twitter", "x", "threads", "bluesky", "bsky", "reddit", "youtube") && identifier.isNotBlank()) {
                return true
            }
        }
        val target = if (trimmed.startsWith("http://", ignoreCase = true) || trimmed.startsWith("https://", ignoreCase = true)) {
            trimmed
        } else if (trimmed.contains('.')) {
            "https://$trimmed"
        } else {
            return false
        }
        return runCatching {
            val uri = URI(target)
            val host = uri.host
            !host.isNullOrBlank() && host.contains('.') && host.length >= 4
        }.getOrDefault(false)
    }

    fun isProfileUrl(url: String): Boolean {
        val trimmed = url.trim().trim('"', '\'')
        if (trimmed.isBlank()) return false
        if (trimmed.contains(':') && !trimmed.contains("://")) {
            val parts = trimmed.split(':', limit = 2)
            val platform = parts[0].trim().lowercase(Locale.US)
            val identifier = parts[1].trim()
            if (platform in setOf("instagram", "facebook", "tiktok", "twitter", "x", "threads", "bluesky", "bsky", "reddit") && identifier.isNotBlank()) {
                return true
            }
        }
        val target = if (!trimmed.startsWith("http://", ignoreCase = true) && !trimmed.startsWith("https://", ignoreCase = true)) {
            "https://$trimmed"
        } else {
            trimmed
        }
        val uri = runCatching { URI(target) }.getOrNull() ?: return false
        val host = (uri.host ?: "").lowercase(Locale.US).removePrefix("www.").removePrefix("m.")
        val path = (uri.path ?: "").lowercase(Locale.US).trimEnd('/')
        val segments = path.split('/').filter { it.isNotBlank() }

        return when {
            host.contains("facebook.com") -> {
                if (path.contains("/watch") || path.contains("/reel") || path.contains("/videos/")) return false
                if (path.contains("/profile.php") || path.contains("/people/")) return true
                val reserved = setOf("watch", "reel", "reels", "videos", "share", "story.php", "photo", "photo.php", "groups", "events", "marketplace", "login", "pages", "hashtag", "posts", "stories", "live")
                segments.size == 1 && segments[0] !in reserved
            }
            host.contains("instagram.com") -> segments.size == 1 && segments[0] !in setOf("reel", "reels", "p", "tv", "stories", "explore")
            host == "x.com" || host == "twitter.com" -> segments.size == 1 && !path.contains("/status/")
            host.contains("threads.net") -> segments.size == 1
            host.contains("tiktok.com") -> segments.size == 1 && segments[0].startsWith("@") && !path.contains("/video/") && !path.contains("/photo/")
            host.contains("bsky.app") -> path.contains("/profile/")
            host.contains("reddit.com") -> path.contains("/user/") || path.contains("/u/")
            else -> false
        }
    }

    suspend fun fetchMetadataAndFormats(
        rawUrl: String,
        cookiesFilePath: String? = null,
    ): Result<MediaMetadata> = withContext(Dispatchers.IO) {
        runCatching {
            val url = if (!rawUrl.contains("://") && !rawUrl.startsWith("www.") && rawUrl.contains(':')) {
                resolveProfileUrl(rawUrl)
            } else {
                normalizeUrl(rawUrl)
            }

            if (isProfileUrl(url)) {
                val verifiedImages = inspectProfilePictures(url, cookiesFilePath)
                val formats = verifiedImages.mapIndexed { idx, img ->
                    StreamFormat(
                        formatId = if (img.enhanceHd) "img_hd_$idx" else "img_$idx",
                        extension = img.extension,
                        width = img.width,
                        height = img.height,
                        fps = null,
                        vcodec = "image",
                        acodec = "none",
                        formatNote = img.label,
                        filesizeBytes = img.filesizeBytes.takeIf { it > 0L },
                        directUrl = img.url,
                    )
                }
                val username = runCatching { URI(url).path.trim('/').split('/').lastOrNull()?.trimStart('@') }.getOrNull() ?: "Profile"
                return@runCatching MediaMetadata(
                    url = url,
                    platform = detectPlatformLabel(url),
                    title = username,
                    uploader = username,
                    durationSeconds = null,
                    thumbnailUrl = verifiedImages.firstOrNull()?.url,
                    viewCount = null,
                    formats = formats,
                )
            }

            val isTikTok = detectPlatformLabel(url) == "TIKTOK"
            val request = YoutubeDLRequest(url).apply {
                addOption("--dump-single-json")
                addOption("--no-playlist")
                addOption("--no-warnings")
                addOption("--no-update")
                addOption("--no-check-certificates")
                addOption("--socket-timeout", "25")
                addOption("--retries", "3")
                addOption("--extractor-retries", "3")
                if (isTikTok) {
                    addOption("--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
                    addOption("--referer", "https://www.tiktok.com/")
                }
                if (!cookiesFilePath.isNullOrBlank() && File(cookiesFilePath).exists()) {
                    addOption("--cookies", cookiesFilePath)
                }
            }

            val response = YoutubeDL.getInstance().execute(request)
            val rawOut = response.out.trim()
            val jsonStart = rawOut.indexOf('{')
            if (jsonStart < 0) {
                val errDetail = response.err.ifBlank { "No metadata returned by extractor." }
                throw RuntimeException(formatDownloadError(errDetail.trim(), detectPlatformLabel(url)))
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

    suspend fun searchYoutube(query: String, limit: Int = 10): Result<List<SearchResultItem>> = withContext(Dispatchers.IO) {
        val trimmed = query.trim()
        if (trimmed.length < 2) return@withContext Result.success(emptyList())
        val boundedLimit = limit.coerceIn(1, 25)
        runCatching {
            val request = YoutubeDLRequest("ytsearch$boundedLimit:$trimmed").apply {
                addOption("--dump-single-json")
                addOption("--extract-flat")
                addOption("--no-playlist")
                addOption("--socket-timeout", 15)
            }
            val response = YoutubeDL.getInstance().execute(request)
            val jsonText = response.out ?: ""
            val json = JSONObject(jsonText)
            val entries = json.optJSONArray("entries") ?: JSONArray()
            val list = mutableListOf<SearchResultItem>()
            for (i in 0 until entries.length()) {
                val item = entries.optJSONObject(i) ?: continue
                val id = item.optString("id").trim()
                if (id.isEmpty()) continue
                val title = item.optString("title").trim()
                if (title.isEmpty() || (title.startsWith("[") && title.endsWith("]"))) continue
                val uploader = item.optString("uploader", item.optString("channel", ""))
                val duration = item.optLong("duration", 0L)
                val durationStr = if (duration > 0) {
                    val m = duration / 60
                    val s = duration % 60
                    "%d:%02d".format(m, s)
                } else null
                var thumb = item.optString("thumbnail", "")
                if (thumb.isEmpty()) {
                    thumb = "https://i.ytimg.com/vi/$id/hqdefault.jpg"
                }
                list.add(
                    SearchResultItem(
                        id = id,
                        url = "https://www.youtube.com/watch?v=$id",
                        title = title,
                        uploader = uploader,
                        durationString = durationStr,
                        thumbnail = thumb,
                    )
                )
            }
            list
        }
    }

    suspend fun fetchSuggestions(query: String, language: String = "en"): List<String> = withContext(Dispatchers.IO) {
        val trimmed = query.trim()
        if (trimmed.length < 2 || trimmed.contains("://") || trimmed.startsWith("www.")) {
            return@withContext emptyList()
        }
        try {
            val encodedQuery = Uri.encode(trimmed)
            val url = URL("https://suggestqueries-clients6.youtube.com/complete/search?client=youtube&ds=yt&hl=$language&q=$encodedQuery")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = 4000
                readTimeout = 4000
                requestMethod = "GET"
                setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
            }
            if (conn.responseCode !in 200..299) {
                conn.disconnect()
                return@withContext emptyList()
            }
            val text = conn.inputStream.bufferedReader().use { it.readText() }
            conn.disconnect()
            val start = text.indexOf('[')
            val end = text.lastIndexOf(']')
            if (start == -1 || end == -1 || end <= start) return@withContext emptyList()
            val jsonArray = JSONArray(text.substring(start, end + 1))
            val suggestions = mutableListOf<String>()
            if (jsonArray.length() > 1) {
                val itemsArray = jsonArray.optJSONArray(1)
                if (itemsArray != null) {
                    for (i in 0 until itemsArray.length()) {
                        val item = itemsArray.opt(i)
                        val phrase = when (item) {
                            is JSONArray -> item.optString(0, "")
                            is String -> item
                            else -> ""
                        }.trim()
                        if (phrase.isNotEmpty() && !suggestions.contains(phrase)) {
                            suggestions.add(phrase)
                        }
                        if (suggestions.size >= 8) break
                    }
                }
            }
            suggestions
        } catch (_: Exception) {
            emptyList()
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

            val platform = detectPlatformLabel(url)
            val isTikTok = platform == "TIKTOK"
            val cookiesPath = options.cookiesFilePath
            val hasCookies = !cookiesPath.isNullOrBlank() && File(cookiesPath).exists()

            fun buildRequest(youtubeExtractorArgs: String?): YoutubeDLRequest = YoutubeDLRequest(url).apply {
                addOption("-o", "${outDir.absolutePath}/%(title).120B [%(id)s].%(ext)s")
                addOption("--concurrent-fragments", options.concurrentFragments.coerceIn(1, 16).toString())
                if (!youtubeExtractorArgs.isNullOrBlank()) {
                    addOption("--extractor-args", youtubeExtractorArgs)
                }
                addOption("--no-warnings")
                addOption("--no-update")
                addOption("--no-check-certificates")
                addOption("--socket-timeout", "30")
                addOption("--retries", "3")
                addOption("--fragment-retries", "5")
                addOption("--extractor-retries", "3")
                addOption("--newline")
                if (isTikTok) {
                    addOption("--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
                    addOption("--referer", "https://www.tiktok.com/")
                }
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
                if (hasCookies) {
                    addOption("--cookies", cookiesPath!!)
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

            val progressCallback: (Float, Long, String) -> Unit = { progress, etaInSeconds, line ->
                val cleanLine = line.trim()
                if (cleanLine.isNotEmpty() && !isIgnoredLine(cleanLine)) {
                    // Only log non-spam status lines; progress numbers update the progress bar smoothly
                    if (!cleanLine.startsWith("[download]") || cleanLine.contains("Destination:") || cleanLine.contains("100%")) {
                        onLog(cleanLine)
                    }
                }
                onProgress(progress.coerceIn(0f, 100f), etaInSeconds, cleanLine)
            }

            fun isYouTube403(text: String?): Boolean {
                val lower = text.orEmpty().lowercase(Locale.US)
                return platform == "YOUTUBE" && (lower.contains("http error 403") || lower.contains("403: forbidden"))
            }

            val fallbackArgs = if (hasCookies) {
                "youtube:player_client=tv_downgraded,web_safari,web_embedded,web"
            } else {
                "youtube:player_client=tv_simply,tv,web_safari,web"
            }

            var response = try {
                YoutubeDL.getInstance().execute(buildRequest(null), processId, progressCallback)
            } catch (ex: Exception) {
                if (isYouTube403(ex.message)) {
                    onLog("[Retry] YouTube returned HTTP 403; rotating player client and retrying...")
                    YoutubeDL.getInstance().execute(buildRequest(fallbackArgs), processId, progressCallback)
                } else {
                    throw ex
                }
            }

            if (response.exitCode != 0 && isYouTube403(response.err)) {
                onLog("[Retry] YouTube returned HTTP 403; rotating player client and retrying...")
                response = YoutubeDL.getInstance().execute(buildRequest(fallbackArgs), processId, progressCallback)
            }

            if (response.exitCode != 0) {
                val errDetail = response.err.ifBlank { "Download exited with code ${response.exitCode}" }
                throw RuntimeException(formatDownloadError(errDetail.trim(), platform))
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

    private fun unescapeEmbeddedUrl(raw: String): String {
        return raw
            .replace("\\/", "/")
            .replace("\\u0026", "&")
            .replace("\\u003d", "=")
            .replace("&amp;", "&")
            .trim()
    }

    private fun upgradePublicAvatarUrl(url: String): List<String> {
        val variants = LinkedHashSet<String>()
        val lowered = url.lowercase(Locale.US)
        if (lowered.contains("pbs.twimg.com/profile_images/")) {
            for (suffix in listOf("_normal.", "_bigger.", "_mini.", "_200x200.")) {
                if (url.contains(suffix)) {
                    variants.add(url.replace(suffix, "."))
                    variants.add(url.replace(suffix, "_400x400."))
                    break
                }
            }
        }
        if ((lowered.contains("yt3.googleusercontent.com") || lowered.contains("yt3.ggpht.com")) &&
            Regex("=s\\d{2,3}(?=[-&]|$)").containsMatchIn(url)
        ) {
            variants.add(Regex("=s\\d{2,3}(?=[-&]|$)").replace(url, "=s1024"))
        }
        variants.add(url)
        return variants.toList()
    }

    private fun estimateImageResolutionScore(url: String): Long {
        val lowered = url.lowercase(Locale.US)
        val isFbAvatar = lowered.contains("/t39.30808-1/") || lowered.contains("/t1.6435-1/")
        val isFbCover = lowered.contains("/t39.30808-6/")
        val bucketPriority = when {
            isFbAvatar -> 2L
            isFbCover -> 0L
            else -> 1L
        }

        val dims = mutableListOf<Int>()
        Regex("""(?:^|[&/?_=.,-])(?:mx|s|p|w)(\d{2,4})x(\d{2,4})""").findAll(lowered).forEach { m ->
            dims.add(maxOf(m.groupValues[1].toInt(), m.groupValues[2].toInt()))
        }
        Regex("""=[sw](\d{2,4})(?:[-&#]|$)""").findAll(lowered).forEach { m ->
            dims.add(m.groupValues[1].toInt())
        }
        if (lowered.contains("pbs.twimg.com/profile_images/")) {
            dims.add(
                when {
                    lowered.contains("_normal.") || lowered.contains("_mini.") -> 48
                    lowered.contains("_bigger.") -> 73
                    lowered.contains("_200x200.") -> 200
                    lowered.contains("_400x400.") -> 400
                    else -> 1080
                }
            )
        }

        val maxDim = dims.maxOrNull() ?: 1080
        val tier = when {
            maxDim >= 600 -> 3L
            maxDim >= 300 -> 2L
            else -> 1L
        }
        return bucketPriority * 1_000_000L + tier * 100_000L + maxDim
    }

    private data class ProbedProfileImage(
        val url: String,
        val label: String,
        val isCover: Boolean,
        val width: Int?,
        val height: Int?,
        val filesizeBytes: Long,
        val extension: String,
        val enhanceHd: Boolean = false,
    ) {
        val pixelArea: Long get() = if (width != null && height != null) width.toLong() * height.toLong() else 0L
    }

    private fun computeHdTargetDimensions(width: Int, height: Int, targetMinSide: Int = 960, maxScale: Float = 4f): Pair<Int, Int> {
        val longest = maxOf(width, height)
        if (longest <= 0 || longest >= targetMinSide) return width to height
        val scale = minOf(maxScale, targetMinSide.toFloat() / longest.toFloat())
        return maxOf(1, Math.round(width * scale)) to maxOf(1, Math.round(height * scale))
    }

    private fun enhanceImageBytesToHd(rawBytes: ByteArray): Pair<ByteArray, String>? {
        val src = BitmapFactory.decodeByteArray(rawBytes, 0, rawBytes.size) ?: return null
        val (targetW, targetH) = computeHdTargetDimensions(src.width, src.height)
        var current: Bitmap = src
        if (targetW > src.width || targetH > src.height) {
            // Progressive 1.5x filtered scaling preserves cleaner contours than a single 4x jump
            var curW = src.width
            var curH = src.height
            while (curW < targetW || curH < targetH) {
                val nextW = minOf(targetW, maxOf(curW + 1, Math.round(curW * 1.5f)))
                val nextH = minOf(targetH, maxOf(curH + 1, Math.round(curH * 1.5f)))
                val scaled = Bitmap.createScaledBitmap(current, nextW, nextH, true)
                if (current !== src) current.recycle()
                current = scaled
                curW = nextW
                curH = nextH
            }
        }
        val out = java.io.ByteArrayOutputStream()
        current.compress(Bitmap.CompressFormat.PNG, 100, out)
        if (current !== src) current.recycle()
        src.recycle()
        return out.toByteArray() to "png"
    }

    private fun extractOwnerProfileCandidates(htmlText: String, baseUrl: String): List<Triple<String, String, Boolean>> {
        val found = LinkedHashMap<String, Triple<String, String, Boolean>>()

        fun addCandidate(raw: String?, label: String, isCover: Boolean = false) {
            if (raw.isNullOrBlank()) return
            val unescaped = unescapeEmbeddedUrl(raw)
            val resolved = if (unescaped.startsWith("http://") || unescaped.startsWith("https://")) {
                unescaped
            } else {
                runCatching { URI(baseUrl).resolve(unescaped).toString() }.getOrDefault(unescaped)
            }
            if ((resolved.startsWith("http://") || resolved.startsWith("https://")) && !isGenericSiteLogo(resolved)) {
                upgradePublicAvatarUrl(resolved).forEachIndexed { idx, variant ->
                    if (!found.containsKey(variant)) {
                        val vLabel = if (idx == 0 && variant != resolved && !label.contains("HD")) "$label (HD)" else label
                        found[variant] = Triple(variant, vLabel, isCover)
                    }
                }
            }
        }

        // Owner-scoped profile avatar & cover fields only (avoids unrelated comment/suggested avatars)
        val ownerPatterns = listOf(
            Triple(Regex(""""hd_profile_pic_url_info"\s*:\s*\{[^\r\n]{0,250}?"url"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (Native HD)", false),
            Triple(Regex(""""hd_profile_pic_versions"\s*:\s*\[[^\r\n]{0,800}?"url"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (HD)", false),
            Triple(Regex(""""profile_pic_url_hd"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (HD)", false),
            Triple(Regex(""""profile_pic_url"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""profilePic(?:Large|Medium|Small|\d+)"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""profile_picture_for_sticky_bar"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""profile_photo"\s*:\s*\{[^\r\n]{0,1200}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""profilePhoto"\s*:\s*\{[^\r\n]{0,1200}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""viewer_image"\s*:\s*\{[^\r\n]{0,250}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+\\?/(?:t39\.30808-1|t1\.6435-1)\\?/[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (Full)", false),
            Triple(Regex("""<svg[^>]+aria-label=[^>]*>(?:(?!</svg>).){0,2500}?<image[^>]+(?:xlink:)?href=["'](https?://scontent[^"']+)["']""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)), "Profile Picture (Header)", false),
            Triple(Regex(""""avatarLarger"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (Large)", false),
            Triple(Regex(""""avatarMedium"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture (Medium)", false),
            Triple(Regex(""""profile_image_url_https"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""(?:icon_img|snoovatar_img)"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Profile Picture", false),
            Triple(Regex(""""cover_photo"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Cover Photo", true),
            Triple(Regex(""""coverPhoto"\s*:\s*\{[^\r\n]{0,600}?"uri"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Cover Photo", true),
            Triple(Regex(""""profile_banner_url"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Cover Banner", true),
            Triple(Regex(""""banner_img"\s*:\s*"(https?:[^"]+)"""", RegexOption.IGNORE_CASE), "Cover Banner", true),
        )
        for ((regex, label, isCover) in ownerPatterns) {
            regex.findAll(htmlText).forEach { addCandidate(it.groupValues[1], label, isCover) }
        }

        val metaPatterns = listOf(
            Regex("""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)""", RegexOption.IGNORE_CASE) to "Profile Picture (OpenGraph)",
            Regex("""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image""", RegexOption.IGNORE_CASE) to "Profile Picture (OpenGraph)",
            Regex("""<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)""", RegexOption.IGNORE_CASE) to "Profile Picture (Meta)",
            Regex("""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']twitter:image""", RegexOption.IGNORE_CASE) to "Profile Picture (Meta)",
        )
        for ((regex, label) in metaPatterns) {
            regex.findAll(htmlText).forEach { addCandidate(it.groupValues[1], label, false) }
        }

        return found.values.sortedWith(
            compareByDescending<Triple<String, String, Boolean>> { if (it.third) 0 else 1 }
                .thenByDescending { estimateImageResolutionScore(it.first) }
        )
    }

    private fun probeProfileImage(
        imageUrl: String,
        label: String,
        isCover: Boolean,
        cookiesFilePath: String?,
    ): ProbedProfileImage? {
        val imgHost = runCatching { URI(imageUrl).host.orEmpty() }.getOrDefault("")
        val conn = (URL(imageUrl).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            instanceFollowRedirects = true
            connectTimeout = 10_000
            readTimeout = 12_000
            setRequestProperty(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            buildCookieHeaderForHost(cookiesFilePath, imgHost)?.let { setRequestProperty("Cookie", it) }
        }
        return try {
            if (conn.responseCode !in 200..299) return null
            val contentType = (conn.contentType ?: "").lowercase(Locale.US)
            if (contentType.isNotBlank() && !contentType.startsWith("image/") && !contentType.contains("octet-stream")) {
                return null
            }
            val bytes = conn.inputStream.use { it.readBytes() }
            if (bytes.size < 512) return null

            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            val w = bounds.outWidth.takeIf { it > 0 }
            val h = bounds.outHeight.takeIf { it > 0 }
            if (w != null && h != null && maxOf(w, h) < 64) return null

            val ext = when {
                contentType.contains("png") -> "png"
                contentType.contains("webp") -> "webp"
                contentType.contains("gif") -> "gif"
                else -> URI(imageUrl).path.substringAfterLast('.', "").lowercase(Locale.US)
                    .takeIf { it in setOf("jpg", "jpeg", "png", "webp", "gif") } ?: "jpg"
            }

            ProbedProfileImage(
                url = imageUrl,
                label = label,
                isCover = isCover,
                width = w,
                height = h,
                filesizeBytes = bytes.size.toLong(),
                extension = ext,
            )
        } catch (_: Exception) {
            null
        } finally {
            conn.disconnect()
        }
    }

    private fun extractFacebookPhotoViewerLinks(htmlText: String): List<Pair<String, Boolean>> {
        val links = LinkedHashMap<String, Boolean>()
        fun addLink(raw: String, isCover: Boolean) {
            var url = unescapeEmbeddedUrl(raw)
            if (url.startsWith("/")) {
                url = "https://www.facebook.com$url"
            }
            if (url.startsWith("http")) {
                links.putIfAbsent(url, isCover)
            }
        }

        val urlPatterns = listOf(
            Regex(""""profile_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo[^"]+)"""", RegexOption.IGNORE_CASE) to false,
            Regex(""""profilePhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo[^"]+)"""", RegexOption.IGNORE_CASE) to false,
            Regex(""""cover_photo"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo[^"]+)"""", RegexOption.IGNORE_CASE) to true,
            Regex(""""coverPhoto"\s*:\s*\{[^\r\n]{0,700}?"url"\s*:\s*"((?:https?:\\?/\\?/[^"]*facebook\.com)?\\?/photo[^"]+)"""", RegexOption.IGNORE_CASE) to true,
        )
        for ((regex, isCover) in urlPatterns) {
            regex.findAll(htmlText).forEach { m -> addLink(m.groupValues[1], isCover) }
        }

        val idPatterns = listOf(
            Regex(""""profile_photo"\s*:\s*\{[^\r\n]{0,300}?"id"\s*:\s*"(\d{6,})"""", RegexOption.IGNORE_CASE) to false,
            Regex(""""cover_photo"\s*:\s*\{[^\r\n]{0,300}?"id"\s*:\s*"(\d{6,})"""", RegexOption.IGNORE_CASE) to true,
        )
        for ((regex, isCover) in idPatterns) {
            regex.findAll(htmlText).forEach { m ->
                val fbid = m.groupValues[1]
                if (links.keys.none { it.contains("fbid=$fbid") }) {
                    addLink("https://www.facebook.com/photo/?fbid=$fbid", isCover)
                }
            }
        }
        return links.entries.map { it.key to it.value }
    }

    private fun extractPhotoViewerImages(htmlText: String, isCover: Boolean): List<Triple<String, String, Boolean>> {
        val label = if (isCover) "Cover Photo (Native HD)" else "Profile Picture (Native HD)"
        val found = LinkedHashSet<String>()
        val patterns = listOf(
            Regex(""""viewer_image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"""", RegexOption.IGNORE_CASE),
            Regex(""""currMedia"\s*:\s*\{[^\r\n]{0,600}?"image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"""", RegexOption.IGNORE_CASE),
            Regex(""""photo_image"\s*:\s*\{[^\r\n]{0,300}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"""", RegexOption.IGNORE_CASE),
            Regex(""""image"\s*:\s*\{[^\r\n]{0,200}?"height"\s*:\s*\d{3,4}[^\r\n]{0,200}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"""", RegexOption.IGNORE_CASE),
            Regex(""""image"\s*:\s*\{[^\r\n]{0,200}?"uri"\s*:\s*"(https?:\\?/\\?/scontent[^"]+)"[^\r\n]{0,200}?"height"\s*:\s*\d{3,4}""", RegexOption.IGNORE_CASE),
            Regex("""<meta[^>]+property=["']og:image["'][^>]+content=["'](https?://scontent[^"']+)["']""", RegexOption.IGNORE_CASE),
            Regex("""<meta[^>]+content=["'](https?://scontent[^"']+)["'][^>]+property=["']og:image["']""", RegexOption.IGNORE_CASE),
        )
        for (regex in patterns) {
            regex.findAll(htmlText).forEach { m ->
                val url = unescapeEmbeddedUrl(m.groupValues[1])
                if (url.startsWith("http") && !isGenericSiteLogo(url)) found.add(url)
            }
        }
        return found.sortedByDescending { estimateImageResolutionScore(it) }.map { Triple(it, label, isCover) }
    }

    private fun inspectProfilePictures(profileUrl: String, cookiesFilePath: String?): List<ProbedProfileImage> {
        val host = runCatching { URI(profileUrl).host.orEmpty() }.getOrDefault("")
        val rawCandidates = LinkedHashMap<String, Triple<String, String, Boolean>>()

        fun fetchPageHtml(targetUrl: String): String? {
            val targetHost = runCatching { URI(targetUrl).host.orEmpty() }.getOrDefault("")
            val conn = (URL(targetUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                instanceFollowRedirects = true
                connectTimeout = 15_000
                readTimeout = 20_000
                setRequestProperty(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                setRequestProperty("DPR", "3")
                setRequestProperty("Sec-CH-DPR", "3")
                setRequestProperty("Viewport-Width", "1920")
                buildCookieHeaderForHost(cookiesFilePath, targetHost)?.let { setRequestProperty("Cookie", it) }
            }
            return try {
                if (conn.responseCode in 200..299) {
                    conn.inputStream.bufferedReader().use { it.readText() }
                } else null
            } finally {
                conn.disconnect()
            }
        }

        runCatching {
            val html = fetchPageHtml(profileUrl)
            if (html != null) {
                extractOwnerProfileCandidates(html, profileUrl).forEach { cand ->
                    rawCandidates.putIfAbsent(cand.first, cand)
                }
                if (host.contains("facebook.com", ignoreCase = true)) {
                    extractFacebookPhotoViewerLinks(html).take(3).forEach { (viewerUrl, isCover) ->
                        runCatching {
                            val viewerHtml = fetchPageHtml(viewerUrl)
                            if (viewerHtml != null) {
                                extractPhotoViewerImages(viewerHtml, isCover).forEach { cand ->
                                    rawCandidates.putIfAbsent(cand.first, cand)
                                }
                            }
                        }
                    }
                }
            }
        }

        val prioritized = rawCandidates.values.sortedWith(
            compareByDescending<Triple<String, String, Boolean>> { if (it.second.contains("Native HD")) 1 else 0 }
                .thenByDescending { if (it.third) 0 else 1 }
                .thenByDescending { estimateImageResolutionScore(it.first) }
        )

        val probed = prioritized.take(16).mapNotNull { (url, label, isCover) ->
            probeProfileImage(url, label, isCover, cookiesFilePath)
        }

        val sorted = probed.sortedWith(
            compareByDescending<ProbedProfileImage> { if (it.isCover) 0 else 1 }
                .thenByDescending { it.pixelArea }
                .thenByDescending { it.filesizeBytes }
        )

        val seenSig = HashSet<String>()
        val deduped = sorted.filter { seenSig.add("${it.isCover}_${it.width}_${it.height}_${it.filesizeBytes}") }.toMutableList()
        val bestAvatar = deduped.firstOrNull { !it.isCover && it.width != null && it.height != null }
        if (bestAvatar != null && bestAvatar.width != null && bestAvatar.height != null && maxOf(bestAvatar.width, bestAvatar.height) < 720) {
            val (hdW, hdH) = computeHdTargetDimensions(bestAvatar.width, bestAvatar.height)
            if (hdW > bestAvatar.width || hdH > bestAvatar.height) {
                deduped.add(
                    0,
                    ProbedProfileImage(
                        url = bestAvatar.url,
                        label = "Profile Picture (HD Enhanced from ${bestAvatar.width}x${bestAvatar.height})",
                        isCover = false,
                        width = hdW,
                        height = hdH,
                        filesizeBytes = 0L,
                        extension = "png",
                        enhanceHd = true,
                    ),
                )
            }
        }
        return deduped
    }

    suspend fun downloadDirectImage(
        imageUrl: String,
        sourceProfileUrl: String?,
        cookiesFilePath: String? = null,
        enhanceHd: Boolean = false,
        onLog: (String) -> Unit,
    ): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val outDir = File(getOutputDirectory(audioOnly = false), "profile_pictures").apply { mkdirs() }
            val safeName = (sourceProfileUrl?.let { runCatching { URI(it).path.trim('/').split('/').lastOrNull()?.trimStart('@') }.getOrNull() } ?: "profile")
                .replace(Regex("[^A-Za-z0-9._-]"), "_")
                .ifBlank { "profile" }
            val imgHost = runCatching { URI(imageUrl).host.orEmpty() }.getOrDefault("")
            var ext = URI(imageUrl).path.substringAfterLast('.', "").lowercase(Locale.US)
                .takeIf { it in setOf("jpg", "jpeg", "png", "webp", "gif") } ?: "jpg"

            val conn = (URL(imageUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                instanceFollowRedirects = true
                connectTimeout = 15_000
                readTimeout = 20_000
                setRequestProperty(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                buildCookieHeaderForHost(cookiesFilePath, imgHost)?.let { setRequestProperty("Cookie", it) }
            }
            var rawBytes = try {
                if (conn.responseCode !in 200..299) {
                    throw RuntimeException("Image download returned HTTP ${conn.responseCode}")
                }
                conn.inputStream.use { it.readBytes() }
            } finally {
                conn.disconnect()
            }

            var suffix = ""
            if (enhanceHd) {
                enhanceImageBytesToHd(rawBytes)?.let { (hdBytes, hdExt) ->
                    rawBytes = hdBytes
                    ext = hdExt
                    suffix = "_HD"
                }
            }

            val dest = File(outDir, "${safeName}${suffix}_${System.currentTimeMillis()}.$ext")
            dest.writeBytes(rawBytes)
            MediaScannerConnection.scanFile(appContext, arrayOf(dest.absolutePath), null, null)
            onLog("[Complete] Image saved: ${dest.name}")
            dest
        }
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
            val hasCookies = !cookiesFilePath.isNullOrBlank() && File(cookiesFilePath).exists()
            onLog(
                if (hasCookies) "[Profile] Resolving verified profile pictures using configured cookies: $profileUrl"
                else "[Profile] Resolving verified public profile pictures: $profileUrl"
            )

            val verified = inspectProfilePictures(profileUrl, cookiesFilePath)
            if (verified.isEmpty()) {
                throw RuntimeException(
                    if (hasCookies) {
                        "No valid profile picture could be resolved with your current session cookies. " +
                            "The account may be private/locked without permission, or cookies may need refreshing."
                    } else {
                        "No valid public profile picture found. For profiles your account is authorized to view, sign in via Web Login or import cookies.txt."
                    }
                )
            }

            val best = verified.first()
            downloadDirectImage(best.url, profileUrl, cookiesFilePath, enhanceHd = best.enhanceHd, onLog = onLog).getOrThrow()
        }
    }

    private fun isIgnoredLine(line: String): Boolean {
        return ignoredLogPatterns.any { line.contains(it, ignoreCase = true) }
    }

    fun cleanErrorMessage(rawError: String): String {
        val lines = rawError.lines()
            .map { it.trim() }
            .filter { line ->
                line.isNotEmpty() &&
                !line.startsWith("WARNING:", ignoreCase = true) &&
                !isIgnoredLine(line)
            }
        val errorLines = lines.filter { it.startsWith("ERROR:", ignoreCase = true) }
        val primary = if (errorLines.isNotEmpty()) errorLines.joinToString("\n") else lines.joinToString("\n")
        return primary.replace(Regex("""^ERROR:\s*""", RegexOption.IGNORE_CASE), "").trim()
            .ifBlank { rawError.trim() }
    }

    fun formatDownloadError(rawError: String, platform: String): String {
        val cleaned = cleanErrorMessage(rawError)
        val lower = cleaned.lowercase(Locale.US)
        if (platform == "TIKTOK" && (lower.contains("unable to extract webpage video data") || lower.contains("unable to extract universal data"))) {
            return "$cleaned\n\nTikTok may be temporarily rate-limiting requests or requires an updated extractor.\n• Update yt-dlp engine via the 3-dot menu\n• Or use 'Web Login' / cookies.txt to authorize extraction."
        }
        if (lower.contains("confirm you are on the latest version using yt-dlp -u") || lower.contains("confirm you are on the latest version using yt-dlp-u")) {
            return "$cleaned\n\nSuggestion: Update the yt-dlp engine from the top menu to download with latest platform extractors."
        }
        return cleaned
    }

    private fun buildFormatSelector(quality: QualityOption, codec: CodecOption): String {
        val heightLimit = when (quality) {
            QualityOption.P2160 -> "[height<=2160]"
            QualityOption.P1440 -> "[height<=1440]"
            QualityOption.P1080 -> "[height<=1080]"
            QualityOption.P720 -> "[height<=720]"
            QualityOption.P480 -> "[height<=480]"
            QualityOption.P360 -> "[height<=360]"
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

data class SearchResultItem(
    val id: String,
    val url: String,
    val title: String,
    val uploader: String,
    val durationString: String?,
    val thumbnail: String?,
)
