package com.universaldownloader.app.engine

import android.os.Build
import com.universaldownloader.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
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

data class VersionPolicyResult(
    val isSupported: Boolean = true,
    val isBlockedVersion: Boolean = false,
    val minSupportedVersion: String = "3.6.0",
    val latestVersion: String = "3.6.0",
    val sunsetMessage: String = "",
    val downloadUrl: String = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest",
    val enforcementMode: String = "block",
)

class AppUpdateChecker {

    companion object {
        val REPO_OWNER: String = BuildConfig.GITHUB_OWNER
        val REPO_NAME: String = BuildConfig.GITHUB_REPO
        val LATEST_RELEASE_API: String = "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest"
        val LATEST_RELEASE_WEB: String = "https://github.com/$REPO_OWNER/$REPO_NAME/releases/latest"
    }

    suspend fun checkVersionPolicy(): VersionPolicyResult = withContext(Dispatchers.IO) {
        val currentVersion = normalizeVersion(BuildConfig.VERSION_NAME)
        var minSupported = "3.6.0"
        var latestVersion = "3.6.0"
        var sunsetMsg = "This version is deprecated. Please download the latest update."
        var downloadUrl = LATEST_RELEASE_WEB
        var mode = "block"
        val blockedList = mutableListOf<String>()

        try {
            val envUrl = System.getenv("UD_VERSION_POLICY_URL")
            val rawUrl = if (!envUrl.isNullOrBlank()) envUrl else "https://raw.githubusercontent.com/$REPO_OWNER/$REPO_NAME/master/version_policy.json"
            val conn = (URL(rawUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 5000
                readTimeout = 5000
                setRequestProperty("Accept", "application/json")
                setRequestProperty("User-Agent", "UniversalDownloader-Android/$currentVersion")
            }
            if (conn.responseCode in 200..299) {
                val json = conn.inputStream.bufferedReader().use { it.readText() }
                val root = JSONObject(json)
                minSupported = root.optString("min_supported_version", minSupported)
                latestVersion = root.optString("latest_version", latestVersion)
                sunsetMsg = root.optString("sunset_message", sunsetMsg)
                downloadUrl = root.optString("download_url", downloadUrl)
                mode = root.optString("enforcement_mode", mode)

                val blockedArr = root.optJSONArray("blocked_versions")
                if (blockedArr != null) {
                    for (i in 0 until blockedArr.length()) {
                        val v = blockedArr.optString(i, "").trim()
                        if (v.isNotEmpty()) {
                            blockedList.add(normalizeVersion(v))
                        }
                    }
                }
            }
        } catch (_: Exception) {}

        val isBlocked = blockedList.any { compareVersions(it, currentVersion) == 0 }
        val belowMin = compareVersions(currentVersion, minSupported) < 0
        val isSupported = mode.equals("allow", ignoreCase = true) || (!isBlocked && !belowMin)

        VersionPolicyResult(
            isSupported = isSupported,
            isBlockedVersion = isBlocked,
            minSupportedVersion = minSupported,
            latestVersion = latestVersion,
            sunsetMessage = sunsetMsg,
            downloadUrl = downloadUrl,
            enforcementMode = mode,
        )
    }

    suspend fun checkForUpdates(): Result<AppUpdateInfo> = withContext(Dispatchers.IO) {
        runCatching {
            val currentVersion = normalizeVersion(BuildConfig.VERSION_NAME)
            try {
                checkViaGitHubApi(currentVersion)
            } catch (apiError: Exception) {
                checkViaLatestRedirect(currentVersion)
                    ?: throw RuntimeException(
                        "Timed out or failed to reach GitHub Releases. Please check your internet connection.",
                        apiError,
                    )
            }
        }
    }

    private fun checkViaGitHubApi(currentVersion: String): AppUpdateInfo {
        val conn = (URL(LATEST_RELEASE_API).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 20_000
            readTimeout = 25_000
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

            return AppUpdateInfo(
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

    private fun checkViaLatestRedirect(currentVersion: String): AppUpdateInfo? {
        val conn = (URL(LATEST_RELEASE_WEB).openConnection() as HttpURLConnection).apply {
            requestMethod = "HEAD"
            instanceFollowRedirects = false
            connectTimeout = 15_000
            readTimeout = 15_000
            setRequestProperty("User-Agent", "UniversalDownloader-Android/$currentVersion")
        }
        return try {
            val location = conn.getHeaderField("Location") ?: return null
            val marker = "/releases/tag/"
            val idx = location.indexOf(marker, ignoreCase = true)
            if (idx < 0) return null
            val tag = location.substring(idx + marker.length).substringBefore('?').substringBefore('/')
            val latestVersion = normalizeVersion(tag)
            if (latestVersion.isBlank()) return null

            val prefersArm64 = Build.SUPPORTED_ABIS.any { it.equals("arm64-v8a", ignoreCase = true) }
            val assetName = if (prefersArm64) "UniversalDownloader-android-arm64.apk" else "UniversalDownloader-android-universal.apk"
            val downloadUrl = "https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/v$latestVersion/$assetName"
            AppUpdateInfo(
                currentVersion = currentVersion,
                latestVersion = latestVersion,
                isUpdateAvailable = compareVersions(latestVersion, currentVersion) > 0,
                releaseTitle = "${BuildConfig.APP_NAME} v$latestVersion",
                releaseUrl = location,
                downloadUrl = downloadUrl,
                assetName = assetName,
                assetSizeBytes = 0L,
                releaseNotes = "",
            )
        } catch (_: Exception) {
            null
        } finally {
            conn.disconnect()
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

    suspend fun downloadApk(
        downloadUrl: String,
        destFile: File,
        expectedBytes: Long = 0L,
        onProgress: (Float) -> Unit,
    ): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val conn = (URL(downloadUrl).openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = true
                connectTimeout = 15_000
                readTimeout = 30_000
                setRequestProperty("User-Agent", "UniversalDownloader-Android/${BuildConfig.VERSION_NAME}")
            }
            try {
                val code = conn.responseCode
                if (code !in 200..299) {
                    throw RuntimeException("APK download failed with HTTP $code")
                }
                val total = conn.contentLengthLong.takeIf { it > 0L } ?: expectedBytes
                destFile.parentFile?.mkdirs()
                conn.inputStream.use { input ->
                    destFile.outputStream().use { output ->
                        val buffer = ByteArray(65_536)
                        var copied = 0L
                        while (true) {
                            val read = input.read(buffer)
                            if (read <= 0) break
                            output.write(buffer, 0, read)
                            copied += read
                            if (total > 0L) {
                                onProgress(((copied * 100f) / total).coerceIn(0f, 100f))
                            }
                        }
                    }
                }
                onProgress(100f)
                destFile
            } finally {
                conn.disconnect()
            }
        }
    }
}
