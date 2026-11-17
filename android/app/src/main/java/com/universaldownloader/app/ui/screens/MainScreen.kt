package com.universaldownloader.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.webkit.MimeTypeMap
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.universaldownloader.app.BuildConfig
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import coil.compose.SubcomposeAsyncImage
import com.universaldownloader.app.model.CodecOption
import com.universaldownloader.app.model.EngineStatus
import com.universaldownloader.app.model.HistoryEntry
import com.universaldownloader.app.model.LogEntry
import com.universaldownloader.app.model.LogSeverity
import com.universaldownloader.app.model.QualityOption
import com.universaldownloader.app.model.QueueItemStatus
import com.universaldownloader.app.model.StreamFormat
import com.universaldownloader.app.ui.components.InfoLabel
import com.universaldownloader.app.ui.components.WebViewCookieLoginDialog
import com.universaldownloader.app.ui.theme.AccentBlue
import com.universaldownloader.app.ui.theme.AccentIndigo
import com.universaldownloader.app.ui.theme.AccentMint
import com.universaldownloader.app.ui.theme.AccentSky
import com.universaldownloader.app.ui.theme.BgDark
import com.universaldownloader.app.ui.theme.BorderSubtle
import com.universaldownloader.app.ui.theme.ErrorRed
import com.universaldownloader.app.ui.theme.SuccessGreen
import com.universaldownloader.app.ui.theme.SurfaceCard
import com.universaldownloader.app.ui.theme.SurfaceCardAlt
import com.universaldownloader.app.ui.theme.TerminalBg
import com.universaldownloader.app.ui.theme.TextMuted
import com.universaldownloader.app.ui.theme.TextPrimary
import com.universaldownloader.app.ui.theme.TextSecondary
import com.universaldownloader.app.ui.theme.WarningAmber
import com.universaldownloader.app.viewmodel.MainUiState
import com.universaldownloader.app.viewmodel.MainViewModel
import java.io.File
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(viewModel: MainViewModel) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    var showUpdateMenu by remember { mutableStateOf(false) }
    var showUpdateDialog by remember { mutableStateOf(false) }

    // Automatically launch native Android APK installer when in-app APK download completes
    LaunchedEffect(state.readyToInstallApkPath) {
        val apkPath = state.readyToInstallApkPath
        if (!apkPath.isNullOrBlank()) {
            viewModel.consumeReadyApkPath()
            installDownloadedApk(context, apkPath)
        }
    }

    Scaffold(
        containerColor = BgDark,
        topBar = {
            Column {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = BgDark,
                        titleContentColor = TextPrimary,
                    ),
                    title = {
                        Column {
                            Text(
                                text = "Universal Downloader",
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Bold,
                                color = TextPrimary,
                            )
                            Text(
                                text = when (state.engineStatus) {
                                    EngineStatus.INITIALIZING -> "Bootstrapping engine..."
                                    EngineStatus.UPDATING -> "Updating yt-dlp..."
                                    EngineStatus.READY -> "v${BuildConfig.VERSION_NAME} • yt-dlp + FFmpeg Ready"
                                    EngineStatus.ERROR -> "Engine error"
                                },
                                fontSize = 11.sp,
                                color = when (state.engineStatus) {
                                    EngineStatus.READY -> SuccessGreen
                                    EngineStatus.ERROR -> ErrorRed
                                    else -> AccentSky
                                },
                            )
                        }
                    },
                    actions = {
                        Box {
                            IconButton(
                                onClick = { showUpdateMenu = true },
                                enabled = !state.isDownloading,
                            ) {
                                if (state.engineStatus == EngineStatus.UPDATING ||
                                    state.engineStatus == EngineStatus.INITIALIZING ||
                                    state.isCheckingAppUpdate
                                ) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(18.dp),
                                        strokeWidth = 2.dp,
                                        color = AccentSky,
                                    )
                                } else {
                                    Icon(
                                        imageVector = Icons.Default.SystemUpdate,
                                        contentDescription = "Updates",
                                        tint = if (state.appUpdateInfo?.isUpdateAvailable == true) AccentIndigo else AccentSky,
                                    )
                                }
                            }

                            DropdownMenu(
                                expanded = showUpdateMenu,
                                onDismissRequest = { showUpdateMenu = false },
                            ) {
                                DropdownMenuItem(
                                    text = { Text("Check App Update (APK)") },
                                    onClick = {
                                        showUpdateMenu = false
                                        viewModel.checkForAppUpdate(silent = false)
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text("Update yt-dlp Engine") },
                                    enabled = state.engineStatus == EngineStatus.READY,
                                    onClick = {
                                        showUpdateMenu = false
                                        viewModel.updateYtDlpEngine()
                                    },
                                )
                            }
                        }
                    },
                )

                // App Update Available Banner
                val update = state.appUpdateInfo
                if (update != null && update.isUpdateAvailable && !state.isUpdateBannerDismissed) {
                    Surface(
                        color = Color(0xFF1E1B4B),
                        border = BorderStroke(1.dp, AccentIndigo),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 4.dp)
                            .clip(RoundedCornerShape(10.dp)),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(AccentIndigo)
                                    .padding(horizontal = 6.dp, vertical = 2.dp),
                            ) {
                                Text("UPDATE", color = Color.White, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                            }
                            Text(
                                text = "v${update.latestVersion} available (current v${update.currentVersion})",
                                color = TextPrimary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(
                                onClick = { showUpdateDialog = true },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
                            ) {
                                Text("Update", color = AccentSky, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            }
                            IconButton(
                                onClick = { viewModel.dismissUpdateBanner() },
                                modifier = Modifier.size(24.dp),
                            ) {
                                Icon(Icons.Default.Close, contentDescription = "Dismiss", tint = TextSecondary, modifier = Modifier.size(15.dp))
                            }
                        }
                    }
                }
            }
        },
        bottomBar = {
            Column {
                // Global Status Bar with Active Task Spinner
                Surface(
                    color = SurfaceCardAlt,
                    border = BorderStroke(0.5.dp, BorderSubtle),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (state.isAnyTaskRunning) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(13.dp),
                                strokeWidth = 2.dp,
                                color = AccentSky,
                            )
                        }
                        Text(
                            text = state.globalStatus,
                            fontSize = 11.sp,
                            color = TextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }

                NavigationBar(containerColor = SurfaceCardAlt) {
                    val navItems = listOf(
                        Triple("Download", Icons.Default.Download, 0),
                        Triple("Streams", Icons.Default.Layers, 1),
                        Triple("History", Icons.Default.History, 2),
                        Triple("Logs", Icons.Default.Terminal, 3),
                    )
                    navItems.forEach { (label, icon, idx) ->
                        NavigationBarItem(
                            selected = state.selectedTab == idx,
                            onClick = { viewModel.selectTab(idx) },
                            icon = { Icon(icon, contentDescription = label) },
                            label = { Text(label, fontSize = 11.sp) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = AccentIndigo,
                                selectedTextColor = AccentIndigo,
                                unselectedIconColor = TextSecondary,
                                unselectedTextColor = TextSecondary,
                                indicatorColor = AccentIndigo.copy(alpha = 0.16f),
                            ),
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when (state.selectedTab) {
                0 -> DownloadTab(state = state, viewModel = viewModel, context = context)
                1 -> StreamsTab(state = state, viewModel = viewModel)
                2 -> HistoryTab(state = state, viewModel = viewModel, context = context)
                3 -> LogsTab(state = state, viewModel = viewModel, context = context)
            }
        }
    }

    val updateInfo = state.appUpdateInfo
    if (showUpdateDialog && updateInfo != null) {
        AlertDialog(
            onDismissRequest = { showUpdateDialog = false },
            containerColor = SurfaceCard,
            shape = RoundedCornerShape(14.dp),
            title = {
                Text(
                    text = "Update Available — v${updateInfo.latestVersion}",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 17.sp,
                )
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = "Installed: v${updateInfo.currentVersion}  →  Latest: v${updateInfo.latestVersion}",
                        color = AccentSky,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                    )
                    if (!updateInfo.assetName.isNullOrBlank()) {
                        val sizeMb = if (updateInfo.assetSizeBytes > 0L) {
                            String.format(Locale.US, " (%.1f MB)", updateInfo.assetSizeBytes / (1024.0 * 1024.0))
                        } else {
                            ""
                        }
                        Text(
                            text = "Package: ${updateInfo.assetName}$sizeMb",
                            color = TextSecondary,
                            fontSize = 12.sp,
                        )
                    }
                    if (updateInfo.releaseNotes.isNotBlank()) {
                        Text(
                            text = updateInfo.releaseNotes.take(600),
                            color = TextSecondary,
                            fontSize = 12.sp,
                            lineHeight = 17.sp,
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (!updateInfo.assetName.isNullOrBlank() && updateInfo.downloadUrl.endsWith(".apk", ignoreCase = true)) {
                            viewModel.downloadUpdateApk()
                        } else {
                            showUpdateDialog = false
                            openExternalUrl(context, updateInfo.downloadUrl)
                        }
                    },
                    enabled = !state.isDownloadingAppUpdate,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
                ) {
                    if (state.isDownloadingAppUpdate) {
                        Text(
                            String.format(Locale.US, "Downloading %.0f%%", state.appUpdateDownloadProgress),
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                        )
                    } else {
                        Text("Download & Install APK", color = Color.White, fontWeight = FontWeight.Bold)
                    }
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        showUpdateDialog = false
                        openExternalUrl(context, updateInfo.releaseUrl)
                    },
                ) {
                    Text("Release Page", color = AccentSky)
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DownloadTab(
    state: MainUiState,
    viewModel: MainViewModel,
    context: Context,
) {
    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // 1. URL Input Card
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceCard),
            shape = RoundedCornerShape(12.dp),
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                InfoLabel(
                    title = "Media URL",
                    explanation = "Paste any video, audio, reel, or playlist URL from 1,000+ supported sites (YouTube, Instagram, TikTok, Facebook, X/Twitter, SoundCloud, Vimeo, Reddit, Twitch, etc.). You can also Share directly from other apps!",
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                )

                OutlinedTextField(
                    value = state.urlInput,
                    onValueChange = { viewModel.onUrlChanged(it) },
                    placeholder = { Text("Paste video, reel, or audio URL...", color = TextMuted, fontSize = 13.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        if (state.urlInput.isNotEmpty()) {
                            IconButton(onClick = { viewModel.onUrlChanged("") }) {
                                Icon(Icons.Default.Close, contentDescription = "Clear", tint = TextSecondary)
                            }
                        }
                    },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = AccentIndigo,
                        unfocusedBorderColor = BorderSubtle,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                    ),
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            val text = clipboard.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()
                            if (!text.isNullOrBlank()) {
                                viewModel.onUrlChanged(text, immediate = true)
                            }
                        },
                        modifier = Modifier.weight(1f),
                        border = BorderStroke(1.dp, BorderSubtle),
                    ) {
                        Icon(Icons.Default.ContentPaste, contentDescription = null, modifier = Modifier.size(16.dp), tint = TextSecondary)
                        Spacer(Modifier.width(6.dp))
                        Text("Paste", color = TextPrimary, fontSize = 13.sp)
                    }

                    Button(
                        onClick = { viewModel.inspectStreams() },
                        enabled = state.urlInput.isNotBlank() && state.engineStatus == EngineStatus.READY && !state.isInspectingStreams && !state.isDownloading,
                        modifier = Modifier.weight(1.3f),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF374151)),
                    ) {
                        if (state.isInspectingStreams) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(15.dp),
                                strokeWidth = 2.dp,
                                color = AccentSky,
                            )
                            Spacer(Modifier.width(6.dp))
                            Text("Inspecting...", fontSize = 13.sp, color = Color.White)
                        } else {
                            Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(16.dp), tint = AccentSky)
                            Spacer(Modifier.width(6.dp))
                            Text("Inspect Streams", fontSize = 13.sp, color = Color.White)
                        }
                    }
                }

                // Smart Clipboard Suggestion Banner
                val clipUrl = state.detectedClipboardUrl
                if (!clipUrl.isNullOrBlank()) {
                    Surface(
                        color = Color(0xFF162032),
                        border = BorderStroke(1.dp, AccentSky),
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(
                                text = "Copied link: $clipUrl",
                                color = Color(0xFFBAE6FD),
                                fontSize = 11.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(
                                onClick = { viewModel.acceptClipboardUrl() },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
                            ) {
                                Text("Load", color = AccentSky, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            }
                            IconButton(
                                onClick = { viewModel.dismissClipboardUrl() },
                                modifier = Modifier.size(22.dp),
                            ) {
                                Icon(Icons.Default.Close, contentDescription = "Dismiss", tint = TextSecondary, modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                }
            }
        }

        // 2. Metadata & Thumbnail Preview Card
        if (state.isFetchingMetadata || state.metadata != null) {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceCardAlt),
                border = BorderStroke(1.dp, AccentBlue),
                shape = RoundedCornerShape(12.dp),
            ) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Thumbnail box with spinner & duration badge
                        Box(
                            modifier = Modifier
                                .width(128.dp)
                                .height(74.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(TerminalBg),
                            contentAlignment = Alignment.Center,
                        ) {
                            val thumb = state.metadata?.thumbnailUrl
                            if (!thumb.isNullOrBlank()) {
                                SubcomposeAsyncImage(
                                    model = thumb,
                                    contentDescription = "Video thumbnail",
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                    loading = {
                                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                            CircularProgressIndicator(
                                                modifier = Modifier.size(22.dp),
                                                strokeWidth = 2.dp,
                                                color = AccentSky,
                                            )
                                        }
                                    },
                                )
                            } else if (state.isFetchingMetadata) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(22.dp),
                                    strokeWidth = 2.dp,
                                    color = AccentSky,
                                )
                            }

                            val dur = state.metadata?.durationFormatted.orEmpty()
                            if (dur.isNotEmpty()) {
                                Box(
                                    modifier = Modifier
                                        .align(Alignment.BottomEnd)
                                        .padding(4.dp)
                                        .clip(RoundedCornerShape(4.dp))
                                        .background(Color(0xDD000000))
                                        .padding(horizontal = 5.dp, vertical = 2.dp),
                                ) {
                                    Text(dur, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                        }

                        // Metadata text
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(4.dp))
                                        .background(AccentBlue)
                                        .padding(horizontal = 6.dp, vertical = 2.dp),
                                ) {
                                    Text(
                                        text = state.metadata?.platform ?: state.preliminaryPlatform.ifEmpty { "MEDIA" },
                                        color = Color.White,
                                        fontSize = 9.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                                if (state.isFetchingMetadata) {
                                    Text("Loading details...", color = TextSecondary, fontSize = 11.sp)
                                }
                            }

                            Text(
                                text = state.metadata?.title ?: "Fetching media details...",
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 14.sp,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )

                            Row(
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                val uploader = state.metadata?.uploader.orEmpty()
                                if (uploader.isNotEmpty()) {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(3.dp),
                                    ) {
                                        Icon(Icons.Default.Person, contentDescription = null, modifier = Modifier.size(12.dp), tint = TextSecondary)
                                        Text(
                                            uploader,
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    }
                                }
                                val views = state.metadata?.viewCountFormatted.orEmpty()
                                if (views.isNotEmpty()) {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(3.dp),
                                    ) {
                                        Icon(Icons.Default.Visibility, contentDescription = null, modifier = Modifier.size(12.dp), tint = TextMuted)
                                        Text(views, color = TextMuted, fontSize = 11.sp)
                                    }
                                }
                            }
                        }
                    }

                    if (state.isFetchingMetadata) {
                        LinearProgressIndicator(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(3.dp)
                                .clip(RoundedCornerShape(2.dp)),
                            color = AccentSky,
                            trackColor = BorderSubtle,
                        )
                    }
                }
            }
        }

        // 3. Download Options Card
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceCard),
            shape = RoundedCornerShape(12.dp),
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Download Options", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = TextPrimary)

                // Quality Dropdown
                var qualityExpanded by remember { mutableStateOf(false) }
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    InfoLabel(
                        title = "Quality",
                        explanation = "Select the target video resolution (1080p, 720p, 480p) or Audio Only (MP3). 'Best Available' automatically downloads the highest resolution available.",
                    )
                    ExposedDropdownMenuBox(
                        expanded = qualityExpanded,
                        onExpandedChange = { qualityExpanded = !qualityExpanded },
                    ) {
                        OutlinedTextField(
                            value = state.options.quality.label,
                            onValueChange = {},
                            readOnly = true,
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = qualityExpanded) },
                            modifier = Modifier
                                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                .fillMaxWidth(),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = AccentIndigo,
                                unfocusedBorderColor = BorderSubtle,
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                            ),
                        )
                        ExposedDropdownMenu(
                            expanded = qualityExpanded,
                            onDismissRequest = { qualityExpanded = false },
                        ) {
                            QualityOption.entries.forEach { q ->
                                DropdownMenuItem(
                                    text = { Text(q.label) },
                                    onClick = {
                                        viewModel.updateQuality(q)
                                        qualityExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }

                // Codec Dropdown
                var codecExpanded by remember { mutableStateOf(false) }
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    InfoLabel(
                        title = "Codec Preference",
                        explanation = "Preferred video compression codec:\n• Auto: Platform default.\n• H.264 / AVC1: Maximum compatibility on all phones, TVs, and players.\n• VP9: High efficiency for 2K/4K.\n• AV1: Next-gen ultra compression.",
                    )
                    ExposedDropdownMenuBox(
                        expanded = codecExpanded,
                        onExpandedChange = { codecExpanded = !codecExpanded },
                    ) {
                        OutlinedTextField(
                            value = state.options.codec.label,
                            onValueChange = {},
                            readOnly = true,
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = codecExpanded) },
                            modifier = Modifier
                                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                .fillMaxWidth(),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = AccentIndigo,
                                unfocusedBorderColor = BorderSubtle,
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                            ),
                        )
                        ExposedDropdownMenu(
                            expanded = codecExpanded,
                            onDismissRequest = { codecExpanded = false },
                        ) {
                            CodecOption.entries.forEach { c ->
                                DropdownMenuItem(
                                    text = { Text(c.label) },
                                    onClick = {
                                        viewModel.updateCodec(c)
                                        codecExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }

                // Concurrent Fragments Slider
                Column {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        InfoLabel(
                            title = "Fragments",
                            explanation = "Number of concurrent stream chunks downloaded in parallel for DASH/HLS streams (1 to 16). Higher values accelerate downloads on fast Wi-Fi/5G connections.",
                        )
                        Text(
                            text = "${state.options.concurrentFragments}x",
                            color = AccentSky,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp,
                        )
                    }
                    Slider(
                        value = state.options.concurrentFragments.toFloat(),
                        onValueChange = { viewModel.updateFragments(it.toInt()) },
                        valueRange = 1f..16f,
                        steps = 14,
                        colors = SliderDefaults.colors(
                            thumbColor = AccentIndigo,
                            activeTrackColor = AccentIndigo,
                        ),
                    )
                }

                // Toggles with Info Icons
                OptionSwitchRow(
                    title = "Embed Metadata",
                    explanation = "Embeds title, artist/uploader, date, description, and chapters directly into the media file's tags (ID3 / MP4 atoms).",
                    checked = state.options.embedMetadata,
                    onCheckedChange = viewModel::updateEmbedMetadata,
                )
                OptionSwitchRow(
                    title = "Embed Cover Art",
                    explanation = "Embeds the high-resolution source thumbnail directly into the downloaded video or MP3 as album artwork.",
                    checked = state.options.embedThumbnail,
                    onCheckedChange = viewModel::updateEmbedThumbnail,
                )
                OptionSwitchRow(
                    title = "Embed Subtitles",
                    explanation = "Embeds available subtitle tracks directly into video files using FFmpeg without burning them into the picture.",
                    checked = state.options.embedSubs,
                    onCheckedChange = viewModel::updateEmbedSubs,
                )
                OptionSwitchRow(
                    title = "Save Thumbnail File",
                    explanation = "Saves the original thumbnail image alongside the downloaded video/audio inside Downloads/UniversalDownloader.",
                    checked = state.options.writeThumbnail,
                    onCheckedChange = viewModel::updateWriteThumbnail,
                )

                // Cookies.txt Authentication Picker & In-App WebView Login
                var showWebLoginDialog by remember { mutableStateOf(false) }
                val cookiesPickerLauncher = rememberLauncherForActivityResult(
                    contract = ActivityResultContracts.OpenDocument(),
                ) { uri ->
                    if (uri != null) {
                        viewModel.importCookiesFromUri(uri)
                    }
                }
                val hasCookies = !state.options.cookiesFilePath.isNullOrBlank()
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            InfoLabel(
                                title = "Cookies & Account Login",
                                explanation = "Sign in directly via the built-in WebView (Instagram, YouTube, TikTok, X, Facebook) or import a Netscape cookies.txt file to unlock login-gated Reels and age-restricted videos.",
                                color = TextPrimary,
                                fontSize = 13.sp,
                            )
                            Text(
                                text = if (hasCookies) "Active: session cookies saved" else "Not configured (anonymous)",
                                color = if (hasCookies) SuccessGreen else TextMuted,
                                fontSize = 11.sp,
                            )
                        }
                        if (hasCookies) {
                            IconButton(
                                onClick = { viewModel.clearCookiesFile() },
                                modifier = Modifier.size(30.dp),
                            ) {
                                Icon(Icons.Default.Close, contentDescription = "Clear Cookies", tint = ErrorRed, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Button(
                            onClick = { showWebLoginDialog = true },
                            modifier = Modifier.weight(1f),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
                        ) {
                            Text("Web Login", fontSize = 12.sp, color = Color.White, fontWeight = FontWeight.SemiBold)
                        }
                        OutlinedButton(
                            onClick = { cookiesPickerLauncher.launch(arrayOf("text/plain", "*/*")) },
                            modifier = Modifier.weight(1f),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                            border = BorderStroke(1.dp, BorderSubtle),
                        ) {
                            Text(if (hasCookies) "Replace File" else "Import cookies.txt", fontSize = 12.sp, color = AccentSky)
                        }
                    }
                }

                if (showWebLoginDialog) {
                    WebViewCookieLoginDialog(
                        onDismiss = { showWebLoginDialog = false },
                        onCookiesSaved = { lines, siteLabel ->
                            showWebLoginDialog = false
                            viewModel.saveWebViewCookies(lines, siteLabel)
                        },
                    )
                }

                // Collapsible Clip Trimmer, Playlist Picker & SponsorBlock Section
                var showAdvanced by remember { mutableStateOf(false) }
                OutlinedButton(
                    onClick = { showAdvanced = !showAdvanced },
                    modifier = Modifier.fillMaxWidth(),
                    border = BorderStroke(1.dp, BorderSubtle),
                ) {
                    Text(
                        text = if (showAdvanced) "Hide Clip Trimmer, Playlist & SponsorBlock" else "Clip Trimmer, Playlist & SponsorBlock (Advanced)",
                        color = AccentSky,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }

                if (showAdvanced) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SurfaceCardAlt)
                            .border(1.dp, BorderSubtle, RoundedCornerShape(8.dp))
                            .padding(10.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                InfoLabel(
                                    title = "Start Time",
                                    explanation = "Optional clip start timestamp (e.g. 00:00:30 or 30). Downloads starting from this timestamp.",
                                )
                                OutlinedTextField(
                                    value = state.options.startTime,
                                    onValueChange = viewModel::updateStartTime,
                                    placeholder = { Text("00:00:30", color = TextMuted, fontSize = 12.sp) },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                InfoLabel(
                                    title = "End Time",
                                    explanation = "Optional clip end timestamp (e.g. 00:02:15 or 135). Precisely trims the video at this point via FFmpeg.",
                                )
                                OutlinedTextField(
                                    value = state.options.endTime,
                                    onValueChange = viewModel::updateEndTime,
                                    placeholder = { Text("00:02:15", color = TextMuted, fontSize = 12.sp) },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                        }

                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            InfoLabel(
                                title = "Playlist Items",
                                explanation = "Select specific playlist items by index or range (e.g. 1,3,5-8). Leave blank to download the full item/playlist.",
                            )
                            OutlinedTextField(
                                value = state.options.playlistItems,
                                onValueChange = viewModel::updatePlaylistItems,
                                placeholder = { Text("e.g. 1,2,5-8", color = TextMuted, fontSize = 12.sp) },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }

                        OptionSwitchRow(
                            title = "SponsorBlock Skip",
                            explanation = "Automatically removes sponsored segments, intros, outros, and self-promotions from YouTube videos.",
                            checked = state.options.sponsorBlockEnabled,
                            onCheckedChange = viewModel::updateSponsorBlock,
                        )
                    }
                }
            }
        }

        // 4. Action Buttons (Download / Queue / Cancel)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = { viewModel.startDownload() },
                enabled = state.urlInput.isNotBlank() && state.engineStatus == EngineStatus.READY && !state.isDownloading && !state.isQueueRunning,
                modifier = Modifier
                    .weight(1f)
                    .height(50.dp),
                shape = RoundedCornerShape(10.dp),
                colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
            ) {
                Icon(Icons.Default.Download, contentDescription = null, tint = Color.White)
                Spacer(Modifier.width(6.dp))
                Text("Download", fontWeight = FontWeight.Bold, fontSize = 14.sp, color = Color.White)
            }

            OutlinedButton(
                onClick = { viewModel.addToQueue() },
                enabled = state.urlInput.isNotBlank(),
                modifier = Modifier.height(50.dp),
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, BorderSubtle),
            ) {
                Text("+ Queue", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = AccentSky)
            }

            if (state.isDownloading || state.isQueueRunning) {
                Button(
                    onClick = { viewModel.cancelDownload() },
                    modifier = Modifier.height(50.dp),
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = ErrorRed),
                ) {
                    Text("Stop", fontWeight = FontWeight.Bold, color = Color.White)
                }
            }
        }

        // 4.5 Download Queue Card (visible when items are queued)
        if (state.queue.isNotEmpty()) {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceCard),
                shape = RoundedCornerShape(12.dp),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "Download Queue (${state.queue.size})",
                            color = TextPrimary,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 14.sp,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Button(
                                onClick = { viewModel.runQueue() },
                                enabled = !state.isQueueRunning && !state.isDownloading && state.engineStatus == EngineStatus.READY,
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
                            ) {
                                Text("Run Queue", fontSize = 11.sp, color = Color.White, fontWeight = FontWeight.Bold)
                            }
                            OutlinedButton(
                                onClick = { viewModel.clearCompletedQueue() },
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                                border = BorderStroke(1.dp, BorderSubtle),
                            ) {
                                Text("Clear", fontSize = 11.sp, color = TextSecondary)
                            }
                        }
                    }

                    state.queue.forEach { qItem ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(SurfaceCardAlt)
                                .padding(8.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Text(
                                    text = qItem.title,
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Medium,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    text = qItem.status.name,
                                    color = when (qItem.status) {
                                        QueueItemStatus.COMPLETED -> SuccessGreen
                                        QueueItemStatus.FAILED -> ErrorRed
                                        QueueItemStatus.DOWNLOADING -> AccentSky
                                        else -> TextMuted
                                    },
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                                if (qItem.status != QueueItemStatus.DOWNLOADING) {
                                    IconButton(
                                        onClick = { viewModel.removeQueueItem(qItem.id) },
                                        modifier = Modifier.size(20.dp),
                                    ) {
                                        Icon(Icons.Default.Close, contentDescription = "Remove", tint = TextMuted, modifier = Modifier.size(13.dp))
                                    }
                                }
                            }
                            LinearProgressIndicator(
                                progress = { (qItem.progress / 100f).coerceIn(0f, 1f) },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(4.dp)
                                    .clip(RoundedCornerShape(2.dp)),
                                color = AccentIndigo,
                                trackColor = BorderSubtle,
                            )
                            Text(qItem.detail, color = TextSecondary, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }

        // 5. Real-Time Progress Card
        if (state.isDownloading || state.downloadStatusText.isNotEmpty()) {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceCard),
                shape = RoundedCornerShape(12.dp),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = state.downloadStatusText.ifEmpty { "Ready" },
                            color = TextPrimary,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 13.sp,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = String.format(Locale.US, "%.1f%%", state.downloadProgress),
                            color = AccentIndigo,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp,
                        )
                    }

                    if (state.isIndeterminateProgress) {
                        LinearProgressIndicator(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(7.dp)
                                .clip(RoundedCornerShape(4.dp)),
                            color = AccentIndigo,
                            trackColor = BorderSubtle,
                        )
                    } else {
                        LinearProgressIndicator(
                            progress = { (state.downloadProgress / 100f).coerceIn(0f, 1f) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(7.dp)
                                .clip(RoundedCornerShape(4.dp)),
                            color = AccentIndigo,
                            trackColor = BorderSubtle,
                        )
                    }

                    if (state.downloadEtaText.isNotEmpty()) {
                        Text(state.downloadEtaText, color = TextSecondary, fontSize = 12.sp)
                    }
                }
            }
        }

        // 6. Inline Live Terminal Preview
        Card(
            colors = CardDefaults.cardColors(containerColor = SurfaceCard),
            shape = RoundedCornerShape(12.dp),
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    InfoLabel(
                        title = "Live Terminal Output",
                        explanation = "Real-time output from the embedded yt-dlp and FFmpeg engine showing milestones, format selection, and diagnostics.",
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                    )
                    OutlinedButton(
                        onClick = {
                            val text = state.logs.takeLast(40).joinToString("\n") { it.formattedText }
                            copyToClipboard(context, "Downloader Logs", text)
                        },
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                        border = BorderStroke(1.dp, BorderSubtle),
                    ) {
                        Icon(Icons.Default.ContentCopy, contentDescription = null, modifier = Modifier.size(12.dp), tint = TextSecondary)
                        Spacer(Modifier.width(4.dp))
                        Text("Copy", fontSize = 11.sp, color = TextPrimary)
                    }
                }

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(130.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(TerminalBg)
                        .border(1.dp, BorderSubtle, RoundedCornerShape(8.dp))
                        .padding(8.dp),
                ) {
                    val recent = state.logs.takeLast(30)
                    if (recent.isEmpty()) {
                        Text(
                            "Engine output will appear here...",
                            color = TextMuted,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                        )
                    } else {
                        SelectionContainer {
                            LazyColumn(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                items(recent, key = { it.id }) { entry ->
                                    Text(
                                        text = entry.formattedText,
                                        color = severityColor(entry.severity),
                                        fontFamily = FontFamily.Monospace,
                                        fontSize = 11.sp,
                                        lineHeight = 15.sp,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun OptionSwitchRow(
    title: String,
    explanation: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        InfoLabel(
            title = title,
            explanation = explanation,
            color = TextPrimary,
            fontSize = 13.sp,
        )
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = AccentIndigo,
            ),
        )
    }
}

@Composable
private fun StreamsTab(
    state: MainUiState,
    viewModel: MainViewModel,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            InfoLabel(
                title = "Available Streams",
                explanation = "Lists every video and audio stream exposed by the platform so you can pick an exact resolution, frame rate, and codec to download.",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp,
            )
            OutlinedButton(
                onClick = { viewModel.inspectStreams() },
                enabled = state.urlInput.isNotBlank() && !state.isInspectingStreams && state.engineStatus == EngineStatus.READY,
                border = BorderStroke(1.dp, BorderSubtle),
            ) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(14.dp), tint = AccentSky)
                Spacer(Modifier.width(4.dp))
                Text("Refresh", fontSize = 12.sp, color = TextPrimary)
            }
        }

        Text(state.streamsHeader, color = TextSecondary, fontSize = 12.sp)

        if (state.isInspectingStreams) {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceCardAlt),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator(color = AccentSky, strokeWidth = 3.dp)
                    Text(
                        "Inspecting available video & audio streams...",
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                    )
                    LinearProgressIndicator(
                        modifier = Modifier
                            .fillMaxWidth(0.75f)
                            .height(4.dp)
                            .clip(RoundedCornerShape(2.dp)),
                        color = AccentIndigo,
                        trackColor = BorderSubtle,
                    )
                }
            }
        } else {
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                items(state.streams, key = { "${it.formatId}_${it.extension}" }) { format ->
                    StreamRowCard(
                        format = format,
                        onDownloadClick = { viewModel.startDownload(explicitFormatId = format.formatId) },
                    )
                }
            }
        }
    }
}

@Composable
private fun StreamRowCard(
    format: StreamFormat,
    onDownloadClick: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        shape = RoundedCornerShape(10.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                // Resolution + Extension pill grouped cleanly in a Row so they never overlap
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = format.resolutionFormatted,
                        color = AccentMint,
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp,
                    )
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(4.dp))
                            .background(BorderSubtle)
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    ) {
                        Text(
                            text = format.extension.uppercase(Locale.US),
                            color = TextSecondary,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                    Text(
                        text = format.filesizeFormatted,
                        color = TextSecondary,
                        fontSize = 12.sp,
                    )
                }
                Text(
                    text = format.codecSummary,
                    color = TextPrimary,
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (!format.formatNote.isNullOrBlank()) {
                    Text(
                        text = format.formatNote,
                        color = TextMuted,
                        fontSize = 11.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }

            Button(
                onClick = onDownloadClick,
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
            ) {
                Icon(Icons.Default.Bolt, contentDescription = null, modifier = Modifier.size(14.dp), tint = Color.White)
                Spacer(Modifier.width(4.dp))
                Text("Get", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
    }
}

@Composable
private fun HistoryTab(
    state: MainUiState,
    viewModel: MainViewModel,
    context: Context,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = state.historySearch,
                onValueChange = { viewModel.onHistorySearchChanged(it) },
                placeholder = { Text("Search downloads...", color = TextMuted, fontSize = 13.sp) },
                singleLine = true,
                modifier = Modifier.weight(1f),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentIndigo,
                    unfocusedBorderColor = BorderSubtle,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                ),
            )
            IconButton(onClick = { viewModel.clearHistory() }) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "Clear History", tint = ErrorRed)
            }
        }

        if (state.isLoadingHistory) {
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(3.dp),
                color = AccentSky,
                trackColor = BorderSubtle,
            )
        }

        if (state.history.isEmpty() && !state.isLoadingHistory) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("No downloads yet.", color = TextMuted, fontSize = 14.sp)
            }
        } else {
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                items(state.history, key = { it.id }) { item ->
                    HistoryRowCard(item = item, context = context)
                }
            }
        }
    }
}

@Composable
private fun HistoryRowCard(item: HistoryEntry, context: Context) {
    Card(
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        shape = RoundedCornerShape(10.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(
                    text = item.title,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 13.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = "${item.platform} • ${item.dateFormatted}",
                    color = TextSecondary,
                    fontSize = 11.sp,
                )
            }

            IconButton(onClick = { openMediaFile(context, item.filePath) }) {
                Icon(Icons.Default.PlayArrow, contentDescription = "Play", tint = AccentBlue)
            }
            IconButton(onClick = { shareMediaFile(context, item.filePath) }) {
                Icon(Icons.Default.Share, contentDescription = "Share", tint = TextSecondary)
            }
        }
    }
}

@Composable
private fun LogsTab(
    state: MainUiState,
    viewModel: MainViewModel,
    context: Context,
) {
    val filteredLogs = remember(state.logs, state.logFilter) {
        val f = state.logFilter.trim()
        if (f.isEmpty()) state.logs else state.logs.filter { it.formattedText.contains(f, ignoreCase = true) }
    }
    val listState = rememberLazyListState()

    LaunchedEffect(filteredLogs.size) {
        if (filteredLogs.isNotEmpty()) {
            listState.animateScrollToItem(filteredLogs.lastIndex)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = state.logFilter,
                onValueChange = { viewModel.onLogFilterChanged(it) },
                placeholder = { Text("Filter logs...", color = TextMuted, fontSize = 13.sp) },
                singleLine = true,
                modifier = Modifier.weight(1f),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentIndigo,
                    unfocusedBorderColor = BorderSubtle,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                ),
            )
            IconButton(
                onClick = {
                    val full = filteredLogs.joinToString("\n") { it.formattedText }
                    copyToClipboard(context, "Universal Downloader Logs", full)
                },
            ) {
                Icon(Icons.Default.ContentCopy, contentDescription = "Copy All", tint = AccentSky)
            }
            IconButton(onClick = { viewModel.clearLogs() }) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "Clear Logs", tint = ErrorRed)
            }
        }

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .clip(RoundedCornerShape(10.dp))
                .background(TerminalBg)
                .border(1.dp, BorderSubtle, RoundedCornerShape(10.dp))
                .padding(10.dp),
        ) {
            SelectionContainer {
                LazyColumn(
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(filteredLogs, key = { it.id }) { entry ->
                        Text(
                            text = entry.formattedText,
                            color = severityColor(entry.severity),
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            lineHeight = 16.sp,
                        )
                    }
                }
            }
        }

        Text(
            text = "Showing ${filteredLogs.size} of ${state.logs.size} log lines",
            color = TextMuted,
            fontSize = 11.sp,
        )
    }
}

private fun severityColor(severity: LogSeverity): Color = when (severity) {
    LogSeverity.ERROR -> ErrorRed
    LogSeverity.WARNING -> WarningAmber
    LogSeverity.SUCCESS -> SuccessGreen
    LogSeverity.DEBUG -> TextSecondary
    LogSeverity.INFO -> AccentSky
}

private fun copyToClipboard(context: Context, label: String, text: String) {
    if (text.isBlank()) return
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText(label, text))
    Toast.makeText(context, "Copied to clipboard", Toast.LENGTH_SHORT).show()
}

private fun openMediaFile(context: Context, path: String) {
    val file = File(path)
    if (!file.exists()) {
        Toast.makeText(context, "File no longer exists on device", Toast.LENGTH_SHORT).show()
        return
    }
    try {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val ext = file.extension.lowercase(Locale.US)
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "video/*"
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mime)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "Open with"))
    } catch (_: Exception) {
        Toast.makeText(context, "No compatible media player found", Toast.LENGTH_SHORT).show()
    }
}

private fun shareMediaFile(context: Context, path: String) {
    val file = File(path)
    if (!file.exists()) {
        Toast.makeText(context, "File no longer exists on device", Toast.LENGTH_SHORT).show()
        return
    }
    try {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val ext = file.extension.lowercase(Locale.US)
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "*/*"
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = mime
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "Share media"))
    } catch (_: Exception) {
        Toast.makeText(context, "Unable to share file", Toast.LENGTH_SHORT).show()
    }
}

private fun openExternalUrl(context: Context, url: String) {
    try {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        context.startActivity(intent)
    } catch (_: Exception) {
        Toast.makeText(context, "Unable to open browser", Toast.LENGTH_SHORT).show()
    }
}

private fun installDownloadedApk(context: Context, apkPath: String) {
    try {
        val file = File(apkPath)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(intent)
    } catch (_: Exception) {
        Toast.makeText(context, "Unable to launch APK installer", Toast.LENGTH_SHORT).show()
    }
}
