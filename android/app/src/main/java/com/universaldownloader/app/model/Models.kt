package com.universaldownloader.app.model

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class QualityOption(val label: String, val value: String) {
    BEST("Best Available (Max)", "best"),
    P1080("1080p Full HD", "1080p"),
    P720("720p HD", "720p"),
    P480("480p SD", "480p"),
    AUDIO_MP3("Audio Only (MP3)", "audio"),
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
) {
    val resolutionFormatted: String
        get() {
            val isAudioOnly = (vcodec == null || vcodec == "none") && acodec != null && acodec != "none"
            if (isAudioOnly) return "Audio Only"
            val w = width
            val h = height
            val base = if (w != null && h != null && w > 0 && h > 0) "${w}x${h}" else (formatNote ?: "Video")
            return if (fps != null && fps > 0) "$base @ ${fps}fps" else base
        }

    val codecSummary: String
        get() {
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
