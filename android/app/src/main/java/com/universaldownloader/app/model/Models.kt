package com.universaldownloader.app.model

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class QualityOption(val label: String, val value: String, val minHeight: Int) {
    BEST("Best Available (Max)", "best", 0),
    P2160("4K (2160p)", "2160p", 2160),
    P1440("2K (1440p)", "1440p", 1440),
    P1080("1080p Full HD", "1080p", 1080),
    P720("720p HD", "720p", 720),
    P480("480p SD", "480p", 480),
    P360("360p", "360p", 360),
    AUDIO_MP3("Audio Only (MP3)", "audio", 0),
}

enum class CodecOption(val label: String, val value: String?) {
    AUTO("Default (Auto)", null),
    H264("H.264 / AVC1 (Universal)", "h264"),
    VP9("VP9 (High Quality)", "vp9"),
    AV1("AV1 (Ultra Compressed)", "av01"),
}

data class DownloadOptions(
    val quality: QualityOption = QualityOption.BEST,
    val codec: CodecOption = CodecOption.AUTO,
    val concurrentFragments: Int = 4,
    val embedMetadata: Boolean = true,
    val embedThumbnail: Boolean = true,
    val embedSubs: Boolean = false,
    val writeThumbnail: Boolean = false,
    val cookiesFilePath: String? = null,
    val startTime: String = "",
    val endTime: String = "",
    val playlistItems: String = "",
    val sponsorBlockEnabled: Boolean = false,
    val explicitFormatId: String? = null,
)

data class MediaMetadata(
    val url: String,
    val platform: String,
    val title: String,
    val uploader: String,
    val durationSeconds: Long?,
    val thumbnailUrl: String?,
    val viewCount: Long?,
    val formats: List<StreamFormat> = emptyList(),
) {
    val durationFormatted: String
        get() {
            val sec = durationSeconds ?: return ""
            if (sec <= 0L) return ""
            val h = sec / 3600
            val m = (sec % 3600) / 60
            val s = sec % 60
            return if (h > 0) {
                String.format(Locale.US, "%d:%02d:%02d", h, m, s)
            } else {
                String.format(Locale.US, "%d:%02d", m, s)
            }
        }

    val viewCountFormatted: String
        get() {
            val v = viewCount ?: return ""
            return when {
                v >= 1_000_000_000 -> String.format(Locale.US, "%.1fB views", v / 1_000_000_000.0)
                v >= 1_000_000 -> String.format(Locale.US, "%.1fM views", v / 1_000_000.0)
                v >= 1_000 -> String.format(Locale.US, "%.1fK views", v / 1_000.0)
                v > 0 -> "$v views"
                else -> ""
            }
        }

    val isProfileMode: Boolean
        get() = formats.isNotEmpty() && formats.all { it.isImage }

    val hasVideoStreams: Boolean
        get() = formats.any { it.isVideo }

    val hasAudioStreams: Boolean
        get() = formats.any { it.isAudioOnly || it.isVideo }

    fun getSupportedQualities(): List<QualityOption> {
        if (isProfileMode) return emptyList()
        val videoFormats = formats.filter { it.isVideo && (it.height ?: 0) > 0 }
        if (videoFormats.isEmpty()) {
            return listOf(QualityOption.BEST, QualityOption.AUDIO_MP3)
        }

        // Support both horizontal and vertical/portrait (Reels/TikTok/Shorts) orientations
        val effectiveMaxHeight = videoFormats.maxOfOrNull {
            val w = it.width ?: 0
            val h = it.height ?: 0
            if (w > 0 && h > 0) minOf(w, h) else maxOf(w, h)
        } ?: 0

        val list = mutableListOf<QualityOption>()
        list.add(QualityOption.BEST)
        if (effectiveMaxHeight >= 2160) list.add(QualityOption.P2160)
        if (effectiveMaxHeight >= 1440) list.add(QualityOption.P1440)
        if (effectiveMaxHeight >= 1080) list.add(QualityOption.P1080)
        if (effectiveMaxHeight >= 720) list.add(QualityOption.P720)
        if (effectiveMaxHeight >= 480) list.add(QualityOption.P480)
        if (effectiveMaxHeight >= 360) list.add(QualityOption.P360)
        list.add(QualityOption.AUDIO_MP3)
        return list
    }

    fun getSupportedCodecs(): List<CodecOption> {
        if (isProfileMode) return emptyList()
        val list = mutableListOf<CodecOption>()
        list.add(CodecOption.AUTO)

        val hasH264 = formats.any {
            val vc = it.vcodec?.lowercase(Locale.US) ?: ""
            vc.contains("avc") || vc.contains("h264") || vc.contains("h.264")
        }
        val hasVp9 = formats.any {
            val vc = it.vcodec?.lowercase(Locale.US) ?: ""
            vc.contains("vp9") || vc.contains("vp09")
        }
        val hasAv1 = formats.any {
            val vc = it.vcodec?.lowercase(Locale.US) ?: ""
            vc.contains("av01") || vc.contains("av1")
        }

        if (hasH264) list.add(CodecOption.H264)
        if (hasVp9) list.add(CodecOption.VP9)
        if (hasAv1) list.add(CodecOption.AV1)

        return list
    }
}

data class StreamFormat(
    val formatId: String,
    val extension: String,
    val width: Int?,
    val height: Int?,
    val fps: Int?,
    val vcodec: String?,
    val acodec: String?,
    val formatNote: String?,
    val filesizeBytes: Long?,
    val directUrl: String? = null,
) {
    val isImage: Boolean
        get() = vcodec.equals("image", ignoreCase = true)

    val isVideo: Boolean
        get() = !isImage && !vcodec.isNullOrBlank() && !vcodec.equals("none", ignoreCase = true)

    val isAudioOnly: Boolean
        get() = !isImage && (vcodec.isNullOrBlank() || vcodec.equals("none", ignoreCase = true)) && !acodec.isNullOrBlank() && !acodec.equals("none", ignoreCase = true)

    val resolutionFormatted: String
        get() {
            if (isImage) {
                val w = width
                val h = height
                return if (w != null && h != null && w > 0 && h > 0) "${w}x${h}" else (formatNote ?: "Image")
            }
            val isAudioOnly = (vcodec == null || vcodec == "none") && acodec != null && acodec != "none"
            if (isAudioOnly) return "Audio Only"
            val w = width
            val h = height
            val base = if (w != null && h != null && w > 0 && h > 0) "${w}x${h}" else (formatNote ?: "Video")
            return if (fps != null && fps > 0) "$base @ ${fps}fps" else base
        }

    val codecSummary: String
        get() {
            if (isImage) {
                return "Image • ${formatNote ?: "Profile Picture"}"
            }
            val parts = mutableListOf<String>()
            if (!vcodec.isNullOrBlank() && vcodec != "none") parts.add("Video: $vcodec")
            if (!acodec.isNullOrBlank() && acodec != "none") parts.add("Audio: $acodec")
            return if (parts.isEmpty()) "Stream #$formatId" else parts.joinToString(" • ")
        }

    val filesizeFormatted: String
        get() {
            val size = filesizeBytes ?: return "—"
            if (size <= 0L) return "—"
            val kb = size / 1024.0
            val mb = kb / 1024.0
            val gb = mb / 1024.0
            return when {
                gb >= 1.0 -> String.format(Locale.US, "%.2f GB", gb)
                mb >= 1.0 -> String.format(Locale.US, "%.1f MB", mb)
                else -> String.format(Locale.US, "%.0f KB", kb)
            }
        }
}

enum class LogSeverity {
    INFO,
    WARNING,
    ERROR,
    SUCCESS,
    DEBUG,
}

data class LogEntry(
    val id: Long,
    val timestamp: String,
    val message: String,
    val severity: LogSeverity,
) {
    val formattedText: String get() = "[$timestamp] $message"

    companion object {
        private var counter = 0L

        fun create(raw: String): LogEntry {
            val ts = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
            return LogEntry(
                id = ++counter,
                timestamp = ts,
                message = raw,
                severity = classify(raw),
            )
        }

        fun classify(message: String): LogSeverity {
            val lower = message.lowercase(Locale.US)
            return when {
                lower.contains("error") || lower.contains("fail") || lower.contains("exception") -> LogSeverity.ERROR
                lower.contains("warning") || lower.contains("warn") || lower.contains("retry") -> LogSeverity.WARNING
                lower.contains("complete") || lower.contains("finished") || lower.contains("success") ||
                    lower.contains("100%") || lower.contains("updated") -> LogSeverity.SUCCESS
                lower.contains("debug") -> LogSeverity.DEBUG
                else -> LogSeverity.INFO
            }
        }
    }
}

data class HistoryEntry(
    val id: Long,
    val url: String,
    val title: String,
    val platform: String,
    val filePath: String,
    val downloadedAt: Long,
) {
    val dateFormatted: String
        get() = SimpleDateFormat("MMM dd, HH:mm", Locale.US).format(Date(downloadedAt))
}

enum class EngineStatus {
    INITIALIZING,
    READY,
    UPDATING,
    ERROR,
}

enum class QueueItemStatus {
    QUEUED,
    DOWNLOADING,
    COMPLETED,
    FAILED,
    CANCELED,
}

data class QueueItem(
    val id: String,
    val url: String,
    val title: String,
    val options: DownloadOptions,
    val status: QueueItemStatus = QueueItemStatus.QUEUED,
    val progress: Float = 0f,
    val detail: String = "Waiting in queue",
)
