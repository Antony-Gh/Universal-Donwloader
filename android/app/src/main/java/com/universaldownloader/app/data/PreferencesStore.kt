package com.universaldownloader.app.data

import android.content.Context
import com.universaldownloader.app.model.CodecOption
import com.universaldownloader.app.model.DownloadOptions
import com.universaldownloader.app.model.QualityOption

class PreferencesStore(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun loadOptions(): DownloadOptions {
        val qualityName = prefs.getString(KEY_QUALITY, QualityOption.BEST.name) ?: QualityOption.BEST.name
        val codecName = prefs.getString(KEY_CODEC, CodecOption.AUTO.name) ?: CodecOption.AUTO.name

        val quality = QualityOption.entries.firstOrNull { it.name == qualityName } ?: QualityOption.BEST
        val codec = CodecOption.entries.firstOrNull { it.name == codecName } ?: CodecOption.AUTO

        return DownloadOptions(
            quality = quality,
            codec = codec,
            concurrentFragments = prefs.getInt(KEY_FRAGMENTS, 4).coerceIn(1, 16),
            embedMetadata = prefs.getBoolean(KEY_EMBED_METADATA, true),
            embedThumbnail = prefs.getBoolean(KEY_EMBED_THUMBNAIL, true),
            embedSubs = prefs.getBoolean(KEY_EMBED_SUBS, false),
            writeThumbnail = prefs.getBoolean(KEY_WRITE_THUMBNAIL, false),
            cookiesFilePath = prefs.getString(KEY_COOKIES_PATH, null)?.takeIf { it.isNotBlank() },
            sponsorBlockEnabled = prefs.getBoolean(KEY_SPONSORBLOCK, false),
        )
    }

    fun saveOptions(options: DownloadOptions) {
        prefs.edit()
            .putString(KEY_QUALITY, options.quality.name)
            .putString(KEY_CODEC, options.codec.name)
            .putInt(KEY_FRAGMENTS, options.concurrentFragments.coerceIn(1, 16))
            .putBoolean(KEY_EMBED_METADATA, options.embedMetadata)
            .putBoolean(KEY_EMBED_THUMBNAIL, options.embedThumbnail)
            .putBoolean(KEY_EMBED_SUBS, options.embedSubs)
            .putBoolean(KEY_WRITE_THUMBNAIL, options.writeThumbnail)
            .putString(KEY_COOKIES_PATH, options.cookiesFilePath ?: "")
            .putBoolean(KEY_SPONSORBLOCK, options.sponsorBlockEnabled)
            .apply()
    }

    fun loadLanguageCode(): String = prefs.getString(KEY_LANGUAGE, "en") ?: "en"

    fun saveLanguageCode(code: String) {
        prefs.edit().putString(KEY_LANGUAGE, code).apply()
    }

    fun getOrCreateInstallId(): String {
        var id = prefs.getString(KEY_INSTALL_ID, null)
        if (id.isNullOrBlank()) {
            id = java.util.UUID.randomUUID().toString()
            prefs.edit().putString(KEY_INSTALL_ID, id).apply()
        }
        return id
    }

    fun isTelemetryEnabled(): Boolean = prefs.getBoolean(KEY_TELEMETRY_ENABLED, true)

    fun setTelemetryEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_TELEMETRY_ENABLED, enabled).apply()
    }

    companion object {
        private const val PREFS_NAME = "universal_downloader_prefs"
        private const val KEY_QUALITY = "quality"
        private const val KEY_CODEC = "codec"
        private const val KEY_FRAGMENTS = "fragments"
        private const val KEY_EMBED_METADATA = "embed_metadata"
        private const val KEY_EMBED_THUMBNAIL = "embed_thumbnail"
        private const val KEY_EMBED_SUBS = "embed_subs"
        private const val KEY_WRITE_THUMBNAIL = "write_thumbnail"
        private const val KEY_COOKIES_PATH = "cookies_path"
        private const val KEY_SPONSORBLOCK = "sponsorblock"
        private const val KEY_LANGUAGE = "language"
        private const val KEY_INSTALL_ID = "install_id"
        private const val KEY_TELEMETRY_ENABLED = "telemetry_enabled"
    }
}
