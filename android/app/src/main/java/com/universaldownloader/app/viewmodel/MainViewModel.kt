package com.universaldownloader.app.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.universaldownloader.app.UniversalDownloaderApp
import com.universaldownloader.app.engine.AppUpdateChecker
import com.universaldownloader.app.engine.AppUpdateInfo
import com.universaldownloader.app.model.CodecOption
import com.universaldownloader.app.model.DownloadOptions
import com.universaldownloader.app.model.EngineStatus
import com.universaldownloader.app.model.HistoryEntry
import com.universaldownloader.app.model.LogEntry
import com.universaldownloader.app.model.MediaMetadata
import com.universaldownloader.app.model.QualityOption
import com.universaldownloader.app.model.StreamFormat
import com.universaldownloader.app.service.DownloadForegroundService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.UUID

data class MainUiState(
    val engineStatus: EngineStatus = EngineStatus.INITIALIZING,
    val engineStatusMessage: String = "Initializing Python, yt-dlp & FFmpeg engine...",
    val urlInput: String = "",
    val options: DownloadOptions = DownloadOptions(),
    val isFetchingMetadata: Boolean = false,
    val metadata: MediaMetadata? = null,
    val preliminaryPlatform: String = "",
    val isInspectingStreams: Boolean = false,
    val streams: List<StreamFormat> = emptyList(),
    val streamsHeader: String = "Enter or paste a media URL to inspect available streams.",
    val isDownloading: Boolean = false,
    val isIndeterminateProgress: Boolean = false,
    val downloadProgress: Float = 0f,
    val downloadStatusText: String = "",
    val downloadEtaText: String = "",
    val logs: List<LogEntry> = emptyList(),
    val logFilter: String = "",
    val history: List<HistoryEntry> = emptyList(),
    val historySearch: String = "",
    val isLoadingHistory: Boolean = false,
    val isCheckingAppUpdate: Boolean = false,
    val appUpdateInfo: AppUpdateInfo? = null,
    val isUpdateBannerDismissed: Boolean = false,
    val detectedClipboardUrl: String? = null,
    val globalStatus: String = "Initializing engine...",
    val selectedTab: Int = 0,
) {
    val isAnyTaskRunning: Boolean
        get() = engineStatus == EngineStatus.INITIALIZING ||
            engineStatus == EngineStatus.UPDATING ||
            isFetchingMetadata ||
            isInspectingStreams ||
            isDownloading ||
            isLoadingHistory ||
            isCheckingAppUpdate
}

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application as UniversalDownloaderApp
    private val repo = app.repository
    private val historyStore = app.historyStore
    private val prefsStore = app.preferencesStore
    private val updateChecker = AppUpdateChecker()

    private val _uiState = MutableStateFlow(MainUiState(options = prefsStore.loadOptions()))
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()

    private var metadataJob: Job? = null
    private var downloadJob: Job? = null
    private var activeProcessId: String? = null
    private var lastFetchedUrl: String? = null
    private var dismissedClipboardUrl: String? = null

    private val supportedClipboardHosts = listOf(
        "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "fb.watch",
        "twitter.com", "x.com", "soundcloud.com", "vimeo.com", "reddit.com", "redd.it",
        "twitch.tv", "threads.net", "pinterest.com", "pin.it", "dailymotion.com",
    )

    init {
        initializeEngine()
        loadHistory()
        checkForAppUpdate(silent = true)
    }

    fun checkForAppUpdate(silent: Boolean = false) {
        if (_uiState.value.isCheckingAppUpdate) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isCheckingAppUpdate = true,
                    globalStatus = if (silent) it.globalStatus else "Checking GitHub Releases for app updates...",
                )
            }
            val result = updateChecker.checkForUpdates()
            result.fold(
                onSuccess = { info ->
                    if (info.isUpdateAvailable) {
                        appendLog("[Info] App update available: v${info.latestVersion} (current: v${info.currentVersion})")
                    } else if (!silent) {
                        appendLog("[Success] App is up to date (v${info.currentVersion}).")
                    }
                    _uiState.update {
                        it.copy(
                            isCheckingAppUpdate = false,
                            appUpdateInfo = info,
                            isUpdateBannerDismissed = if (info.isUpdateAvailable) false else it.isUpdateBannerDismissed,
                            globalStatus = when {
                                info.isUpdateAvailable -> "App update available: v${info.latestVersion}"
                                !silent -> "App is up to date (v${info.currentVersion})"
                                else -> it.globalStatus
                            },
                        )
                    }
                },
                onFailure = { err ->
                    if (!silent) {
                        appendLog("[Warning] App update check failed: ${err.message}")
                    }
                    _uiState.update {
                        it.copy(
                            isCheckingAppUpdate = false,
                            globalStatus = if (silent) it.globalStatus else "Update check failed",
                        )
                    }
                },
            )
        }
    }

    fun dismissUpdateBanner() {
        _uiState.update { it.copy(isUpdateBannerDismissed = true) }
    }

    fun onClipboardTextDetected(rawText: String) {
        val candidate = repo.normalizeUrl(rawText)
        if (candidate.isBlank() || (!candidate.startsWith("http://") && !candidate.startsWith("https://"))) {
            return
        }
        val lower = candidate.lowercase(Locale.US)
        if (supportedClipboardHosts.none { lower.contains(it) }) return
        if (candidate == _uiState.value.urlInput.trim() || candidate == dismissedClipboardUrl) return

        _uiState.update { it.copy(detectedClipboardUrl = candidate) }
    }

    fun acceptClipboardUrl() {
        val url = _uiState.value.detectedClipboardUrl ?: return
        _uiState.update { it.copy(detectedClipboardUrl = null) }
        onUrlChanged(url, immediate = true)
    }

    fun dismissClipboardUrl() {
        dismissedClipboardUrl = _uiState.value.detectedClipboardUrl
        _uiState.update { it.copy(detectedClipboardUrl = null) }
    }

    private fun initializeEngine() {
        viewModelScope.launch {
            appendLog("Bootstrapping embedded Python 3, yt-dlp & FFmpeg runtime...")
            val result = repo.initEngine()
            result.fold(
                onSuccess = {
                    _uiState.update {
                        it.copy(
                            engineStatus = EngineStatus.READY,
                            engineStatusMessage = "Engine ready (yt-dlp + FFmpeg)",
                            globalStatus = "Ready",
                        )
                    }
                    appendLog("[Success] Embedded yt-dlp & FFmpeg runtime ready.")
                    // If a URL was already shared while engine was starting, fetch metadata now
                    val pendingUrl = _uiState.value.urlInput
                    if (pendingUrl.isNotBlank()) {
                        triggerMetadataFetch(pendingUrl, immediate = true)
                    }
                },
                onFailure = { err ->
                    val msg = err.message ?: "Unknown engine initialization failure"
                    _uiState.update {
                        it.copy(
                            engineStatus = EngineStatus.ERROR,
                            engineStatusMessage = "Engine init failed: $msg",
                            globalStatus = "Engine error: $msg",
                        )
                    }
                    appendLog("[Error] Failed to initialize engine: $msg")
                },
            )
        }
    }

    fun updateYtDlpEngine() {
        if (_uiState.value.engineStatus == EngineStatus.UPDATING || _uiState.value.isDownloading) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    engineStatus = EngineStatus.UPDATING,
                    globalStatus = "Updating yt-dlp engine...",
                )
            }
            appendLog("Checking for yt-dlp engine updates...")
            val result = repo.updateEngine()
            result.fold(
                onSuccess = { message ->
                    appendLog("[Success] $message")
                    _uiState.update {
                        it.copy(
                            engineStatus = EngineStatus.READY,
                            globalStatus = message,
                        )
                    }
                },
                onFailure = { err ->
                    val msg = err.message ?: "Update failed"
                    appendLog("[Error] Engine update failed: $msg")
                    _uiState.update {
                        it.copy(
                            engineStatus = EngineStatus.READY,
                            globalStatus = "Update failed: $msg",
                        )
                    }
                },
            )
        }
    }

    fun selectTab(index: Int) {
        _uiState.update { it.copy(selectedTab = index) }
    }

    fun onUrlChanged(newValue: String, immediate: Boolean = false) {
        _uiState.update { it.copy(urlInput = newValue) }
        triggerMetadataFetch(newValue, immediate)
    }

    fun onSharedTextReceived(sharedText: String) {
        val cleaned = repo.normalizeUrl(sharedText)
        if (cleaned.isNotBlank()) {
            _uiState.update { it.copy(urlInput = cleaned, selectedTab = 0) }
            if (_uiState.value.engineStatus == EngineStatus.READY) {
                triggerMetadataFetch(cleaned, immediate = true)
            }
        }
    }

    private fun triggerMetadataFetch(rawInput: String, immediate: Boolean) {
        metadataJob?.cancel()

        val cleaned = repo.normalizeUrl(rawInput)
        if (cleaned.isBlank() || (!cleaned.startsWith("http://") && !cleaned.startsWith("https://"))) {
            lastFetchedUrl = null
            _uiState.update {
                it.copy(
                    isFetchingMetadata = false,
                    metadata = null,
                    preliminaryPlatform = "",
                )
            }
            return
        }

        if (cleaned == lastFetchedUrl && _uiState.value.metadata != null) {
            return
        }

        if (_uiState.value.engineStatus != EngineStatus.READY) {
            return
        }

        metadataJob = viewModelScope.launch {
            if (!immediate) {
                delay(450)
            }
            lastFetchedUrl = cleaned
            val platform = repo.detectPlatformLabel(cleaned)
            _uiState.update {
                it.copy(
                    isFetchingMetadata = true,
                    preliminaryPlatform = platform,
                    metadata = null,
                    globalStatus = "Fetching media metadata & thumbnail...",
                )
            }

            val result = repo.fetchMetadataAndFormats(cleaned, _uiState.value.options.cookiesFilePath)
            result.fold(
                onSuccess = { meta ->
                    _uiState.update {
                        it.copy(
                            isFetchingMetadata = false,
                            metadata = meta,
                            streams = meta.formats,
                            streamsHeader = "Found ${meta.formats.size} streams for: ${meta.title}",
                            globalStatus = "Loaded: ${meta.title}",
                        )
                    }
                },
                onFailure = { err ->
                    appendLog("[Warning] Metadata preview skipped: ${err.message}")
                    _uiState.update {
                        it.copy(
                            isFetchingMetadata = false,
                            globalStatus = "Ready to download",
                        )
                    }
                },
            )
        }
    }

    fun inspectStreams() {
        val cleaned = repo.normalizeUrl(_uiState.value.urlInput)
        if (cleaned.isBlank() || _uiState.value.engineStatus != EngineStatus.READY) return

        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    selectedTab = 1,
                    isInspectingStreams = true,
                    streamsHeader = "Inspecting available video & audio streams...",
                    globalStatus = "Inspecting stream formats...",
                )
            }

            val result = repo.fetchMetadataAndFormats(cleaned, _uiState.value.options.cookiesFilePath)
            result.fold(
                onSuccess = { meta ->
                    lastFetchedUrl = cleaned
                    _uiState.update {
                        it.copy(
                            isInspectingStreams = false,
                            metadata = meta,
                            streams = meta.formats,
                            streamsHeader = "Found ${meta.formats.size} streams for: ${meta.title}",
                            globalStatus = "Found ${meta.formats.size} streams available.",
                        )
                    }
                },
                onFailure = { err ->
                    val msg = err.message ?: "Inspection failed"
                    appendLog("[Error] Stream inspection failed: $msg")
                    _uiState.update {
                        it.copy(
                            isInspectingStreams = false,
                            streamsHeader = "Inspection failed: $msg",
                            globalStatus = "Inspection failed",
                        )
                    }
                },
            )
        }
    }

    private fun updateAndPersistOptions(transform: (DownloadOptions) -> DownloadOptions) {
        _uiState.update { state ->
            val updated = transform(state.options)
            prefsStore.saveOptions(updated)
            state.copy(options = updated)
        }
    }

    fun updateQuality(quality: QualityOption) {
        updateAndPersistOptions { it.copy(quality = quality, explicitFormatId = null) }
    }

    fun updateCodec(codec: CodecOption) {
        updateAndPersistOptions { it.copy(codec = codec) }
    }

    fun updateFragments(count: Int) {
        updateAndPersistOptions { it.copy(concurrentFragments = count.coerceIn(1, 16)) }
    }

    fun updateEmbedMetadata(enabled: Boolean) {
        updateAndPersistOptions { it.copy(embedMetadata = enabled) }
    }

    fun updateEmbedThumbnail(enabled: Boolean) {
        updateAndPersistOptions { it.copy(embedThumbnail = enabled) }
    }

    fun updateEmbedSubs(enabled: Boolean) {
        updateAndPersistOptions { it.copy(embedSubs = enabled) }
    }

    fun updateWriteThumbnail(enabled: Boolean) {
        updateAndPersistOptions { it.copy(writeThumbnail = enabled) }
    }

    fun importCookiesFromUri(uri: android.net.Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val dest = java.io.File(app.filesDir, "cookies.txt")
                app.contentResolver.openInputStream(uri)?.use { input ->
                    dest.outputStream().use { output -> input.copyTo(output) }
                }
                updateAndPersistOptions { it.copy(cookiesFilePath = dest.absolutePath) }
                appendLog("[Success] Imported cookies.txt for authenticated downloads.")
            } catch (e: Exception) {
                appendLog("[Error] Failed to import cookies file: ${e.message}")
            }
        }
    }

    fun clearCookiesFile() {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                java.io.File(app.filesDir, "cookies.txt").delete()
            } catch (_: Exception) {
            }
            updateAndPersistOptions { it.copy(cookiesFilePath = null) }
            appendLog("Cleared cookies.txt authentication file.")
        }
    }

    fun startDownload(explicitFormatId: String? = null) {
        val state = _uiState.value
        val cleaned = repo.normalizeUrl(state.urlInput)
        if (cleaned.isBlank() || state.isDownloading || state.engineStatus != EngineStatus.READY) return

        val effectiveOptions = state.options.copy(explicitFormatId = explicitFormatId)
        val processId = "dl_${UUID.randomUUID()}"
        activeProcessId = processId

        val displayTitle = state.metadata?.title ?: cleaned
        DownloadForegroundService.start(app, "Starting: $displayTitle")

        _uiState.update {
            it.copy(
                selectedTab = 0,
                isDownloading = true,
                isIndeterminateProgress = true,
                downloadProgress = 0f,
                downloadStatusText = "Resolving streams & starting download...",
                downloadEtaText = "ETA: --:--",
                globalStatus = "Starting download...",
            )
        }

        downloadJob = viewModelScope.launch {
            var lastNotifMs = 0L

            val result = repo.download(
                rawUrl = cleaned,
                options = effectiveOptions,
                processId = processId,
                onProgress = { percent, etaSeconds, line ->
                    val isPostProcessing = line.contains("[Merger]", ignoreCase = true) ||
                        line.contains("[ExtractAudio]", ignoreCase = true) ||
                        line.contains("[Metadata]", ignoreCase = true) ||
                        line.contains("[EmbedThumbnail]", ignoreCase = true)

                    val etaFormatted = if (etaSeconds > 0) {
                        String.format(Locale.US, "ETA: %d:%02d", etaSeconds / 60, etaSeconds % 60)
                    } else {
                        "ETA: --:--"
                    }

                    val statusLabel = when {
                        isPostProcessing -> "Processing & merging with FFmpeg..."
                        percent > 0f -> String.format(Locale.US, "Downloading... %.1f%%", percent)
                        else -> "Connecting & resolving stream..."
                    }

                    _uiState.update {
                        it.copy(
                            isIndeterminateProgress = isPostProcessing || percent <= 0f,
                            downloadProgress = percent,
                            downloadStatusText = statusLabel,
                            downloadEtaText = etaFormatted,
                            globalStatus = statusLabel,
                        )
                    }

                    val now = System.currentTimeMillis()
                    if (now - lastNotifMs >= 500L || percent >= 100f) {
                        lastNotifMs = now
                        DownloadForegroundService.updateProgress(
                            context = app,
                            title = "$statusLabel — $displayTitle",
                            progress = percent.toInt(),
                            indeterminate = isPostProcessing || percent <= 0f,
                        )
                    }
                },
                onLog = { logLine ->
                    appendLog(logLine)
                },
            )

            activeProcessId = null

            result.fold(
                onSuccess = { savedFile ->
                    val finalTitle = _uiState.value.metadata?.title ?: savedFile?.nameWithoutExtension ?: cleaned
                    val platform = _uiState.value.metadata?.platform ?: repo.detectPlatformLabel(cleaned)
                    if (savedFile != null) {
                        withContext(Dispatchers.IO) {
                            historyStore.record(cleaned, finalTitle, platform, savedFile.absolutePath)
                        }
                        loadHistory()
                    }
                    DownloadForegroundService.stop(app, "Downloaded: $finalTitle")
                    _uiState.update {
                        it.copy(
                            isDownloading = false,
                            isIndeterminateProgress = false,
                            downloadProgress = 100f,
                            downloadStatusText = "Download finished!",
                            downloadEtaText = "Saved to Downloads/UniversalDownloader",
                            globalStatus = "Downloaded: $finalTitle",
                        )
                    }
                },
                onFailure = { err ->
                    val errMsg = err.message ?: "Download failed"
                    appendLog("[Error] $errMsg")
                    DownloadForegroundService.stop(app, "Download failed")
                    _uiState.update {
                        it.copy(
                            isDownloading = false,
                            isIndeterminateProgress = false,
                            downloadStatusText = "Failed: $errMsg",
                            globalStatus = "Download failed",
                        )
                    }
                },
            )
        }
    }

    fun cancelDownload() {
        activeProcessId?.let { repo.cancelDownload(it) }
        downloadJob?.cancel()
        activeProcessId = null
        DownloadForegroundService.stop(app)
        appendLog("[Warning] Download canceled by user.")
        _uiState.update {
            it.copy(
                isDownloading = false,
                isIndeterminateProgress = false,
                downloadStatusText = "Download canceled.",
                globalStatus = "Download canceled",
            )
        }
    }

    fun onLogFilterChanged(filter: String) {
        _uiState.update { it.copy(logFilter = filter) }
    }

    fun clearLogs() {
        _uiState.update { it.copy(logs = emptyList()) }
    }

    fun onHistorySearchChanged(query: String) {
        _uiState.update { it.copy(historySearch = query) }
        loadHistory(query)
    }

    fun loadHistory(search: String? = _uiState.value.historySearch) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingHistory = true) }
            val records = withContext(Dispatchers.IO) {
                historyStore.query(search)
            }
            _uiState.update {
                it.copy(
                    history = records,
                    isLoadingHistory = false,
                )
            }
        }
    }

    fun clearHistory() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                historyStore.clearAll()
            }
            loadHistory("")
            _uiState.update { it.copy(historySearch = "") }
        }
    }

    private fun appendLog(message: String) {
        if (message.isBlank()) return
        val entry = LogEntry.create(message)
        _uiState.update { current ->
            val updated = if (current.logs.size >= 2000) {
                current.logs.drop(200) + entry
            } else {
                current.logs + entry
            }
            current.copy(logs = updated)
        }
    }
}
