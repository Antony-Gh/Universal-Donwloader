package com.universaldownloader.app.engine

import android.os.Build
import com.universaldownloader.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class AppUpdateInfo(
    val currentVersion: String,
    val latestVersion: String,
    val isUpdateAvailable: Boolean,
    val releaseTitle: String,
    val releaseUrl: String,
    val downloadUrl: String,
    val assetName: String?,
    val assetSizeBytes: Long,
    val releaseNotes: String,
)

class AppUpdateChecker {

    companion object {
        val REPO_OWNER: String = BuildConfig.GITHUB_OWNER
        val REPO_NAME: String = BuildConfig.GITHUB_REPO
        val LATEST_RELEASE_API: String = "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest"
        val LATEST_RELEASE_WEB: String = "https://github.com/$REPO_OWNER/$REPO_NAME/releases/latest"
    }

    suspend fun checkForUpdates(): Result<AppUpdateInfo> = withContext(Dispatchers.IO) {
        runCatching {
            val currentVersion = normalizeVersion(BuildConfig.VERSION_NAME)
            val conn = (URL(LATEST_RELEASE_API).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 12_000
                readTimeout = 12_000
                setRequestProperty("Accept", "application/vnd.github+json")
                setRequestProperty("User-Agent", "UniversalDownloader-Android/$currentVersion")
            }

            try {
                val code = conn.responseCode
                if (code !in 200..299) {
                    throw RuntimeException("GitHub API returned HTTP $code")
                }

                val body = conn.inputStream.bufferedReader().use { it.readText() }
                val root = JSONObject(body)

                val tagName = root.optString("tag_name", "")
                val latestVersion = normalizeVersion(tagName).ifEmpty { currentVersion }
                val releaseTitle = root.optString("name", tagName).ifBlank { "v$latestVersion" }
                val releaseUrl = root.optString("html_url", LATEST_RELEASE_WEB).ifBlank { LATEST_RELEASE_WEB }
                val releaseNotes = root.optString("body", "")

                var downloadUrl = releaseUrl
                var matchedAssetName: String? = null
                var matchedAssetSize = 0L

                val assetsArr = root.optJSONArray("assets")
                if (assetsArr != null) {
                    val apkAssets = mutableListOf<Triple<String, String, Long>>()
                    for (i in 0 until assetsArr.length()) {
                        val obj = assetsArr.optJSONObject(i) ?: continue
                        val name = obj.optString("name", "")
                        val url = obj.optString("browser_download_url", "")
                        val size = obj.optLong("size", 0L)
                        if (name.endsWith(".apk", ignoreCase = true) && url.isNotBlank()) {
                            apkAssets.add(Triple(name, url, size))
                        }
                    }

                    val prefersArm64 = Build.SUPPORTED_ABIS.any { it.equals("arm64-v8a", ignoreCase = true) }
                    val best = if (prefersArm64) {
                        apkAssets.firstOrNull { it.first.contains("arm64", ignoreCase = true) }
                            ?: apkAssets.firstOrNull { it.first.contains("universal", ignoreCase = true) }
                            ?: apkAssets.firstOrNull()
                    } else {
                        apkAssets.firstOrNull { it.first.contains("universal", ignoreCase = true) }
                            ?: apkAssets.firstOrNull()
                    }

                    if (best != null) {
                        matchedAssetName = best.first
                        downloadUrl = best.second
                        matchedAssetSize = best.third
                    }
                }

                AppUpdateInfo(
                    currentVersion = currentVersion,
                    latestVersion = latestVersion,
                    isUpdateAvailable = compareVersions(latestVersion, currentVersion) > 0,
                    releaseTitle = releaseTitle,
                    releaseUrl = releaseUrl,
                    downloadUrl = downloadUrl,
                    assetName = matchedAssetName,
                    assetSizeBytes = matchedAssetSize,
                    releaseNotes = releaseNotes,
                )
            } finally {
                conn.disconnect()
            }
        }
    }

    private fun normalizeVersion(raw: String): String {
        val cleaned = raw.trim().trimStart('v', 'V')
        val dashIdx = cleaned.indexOf('-')
        return if (dashIdx > 0) cleaned.substring(0, dashIdx) else cleaned
    }

    private fun compareVersions(a: String, b: String): Int {
        val partsA = normalizeVersion(a).split('.').map { it.toIntOrNull() ?: 0 }
        val partsB = normalizeVersion(b).split('.').map { it.toIntOrNull() ?: 0 }
        val maxLen = maxOf(partsA.size, partsB.size)
        for (i in 0 until maxLen) {
            val va = partsA.getOrElse(i) { 0 }
            val vb = partsB.getOrElse(i) { 0 }
            if (va != vb) return va.compareTo(vb)
        }
        return 0
    }
}
