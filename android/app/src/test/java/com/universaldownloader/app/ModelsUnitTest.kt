package com.universaldownloader.app

import com.universaldownloader.app.model.LogEntry
import com.universaldownloader.app.model.LogSeverity
import com.universaldownloader.app.model.MediaMetadata
import com.universaldownloader.app.model.StreamFormat
import org.junit.Assert.assertEquals
import org.junit.Test

class ModelsUnitTest {

    @Test
    fun mediaMetadata_formatsDurationAndViews() {
        val meta = MediaMetadata(
            url = "https://youtu.be/abc",
            platform = "YOUTUBE",
            title = "Sample",
            uploader = "Creator",
            durationSeconds = 3725L,
            thumbnailUrl = null,
            viewCount = 2_500_000L,
        )
        assertEquals("1:02:05", meta.durationFormatted)
        assertEquals("2.5M views", meta.viewCountFormatted)
    }

    @Test
    fun streamFormat_formatsResolutionAndAudioOnly() {
        val video = StreamFormat(
            formatId = "137",
            extension = "mp4",
            width = 1920,
            height = 1080,
            fps = 60,
            vcodec = "avc1.640028",
            acodec = "none",
            formatNote = "1080p60",
            filesizeBytes = 104_857_600L,
        )
        assertEquals("1920x1080 @ 60fps", video.resolutionFormatted)
        assertEquals("100.0 MB", video.filesizeFormatted)

        val audio = StreamFormat(
            formatId = "140",
            extension = "m4a",
            width = null,
            height = null,
            fps = null,
            vcodec = "none",
            acodec = "mp4a.40.2",
            formatNote = "medium",
            filesizeBytes = 3_145_728L,
        )
        assertEquals("Audio Only", audio.resolutionFormatted)
        assertEquals("3.0 MB", audio.filesizeFormatted)
    }

    @Test
    fun logEntry_classifiesSeveritiesAccurately() {
        assertEquals(LogSeverity.ERROR, LogEntry.classify("[Error] Download failed"))
        assertEquals(LogSeverity.WARNING, LogEntry.classify("[Warning] Retrying..."))
        assertEquals(LogSeverity.SUCCESS, LogEntry.classify("[Complete] Saved file"))
        assertEquals(LogSeverity.INFO, LogEntry.classify("Starting download..."))
    }
}
