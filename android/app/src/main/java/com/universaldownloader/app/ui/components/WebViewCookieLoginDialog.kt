package com.universaldownloader.app.ui.components

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.universaldownloader.app.ui.theme.AccentIndigo
import com.universaldownloader.app.ui.theme.AccentSky
import com.universaldownloader.app.ui.theme.BgDark
import com.universaldownloader.app.ui.theme.BorderSubtle
import com.universaldownloader.app.ui.theme.SurfaceCard
import com.universaldownloader.app.ui.theme.TextPrimary
import com.universaldownloader.app.ui.theme.TextSecondary

data class LoginSitePreset(
    val label: String,
    val loginUrl: String,
    val cookieDomains: List<String>,
)

val LoginSitePresets = listOf(
    LoginSitePreset(
        label = "Instagram",
        loginUrl = "https://www.instagram.com/accounts/login/",
        cookieDomains = listOf("https://www.instagram.com", "https://instagram.com", "https://i.instagram.com"),
    ),
    LoginSitePreset(
        label = "YouTube",
        loginUrl = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fm.youtube.com%2F",
        cookieDomains = listOf("https://www.youtube.com", "https://m.youtube.com", "https://youtube.com", "https://accounts.google.com"),
    ),
    LoginSitePreset(
        label = "TikTok",
        loginUrl = "https://www.tiktok.com/login",
        cookieDomains = listOf("https://www.tiktok.com", "https://m.tiktok.com", "https://tiktok.com"),
    ),
    LoginSitePreset(
        label = "X / Twitter",
        loginUrl = "https://x.com/i/flow/login",
        cookieDomains = listOf("https://x.com", "https://twitter.com"),
    ),
    LoginSitePreset(
        label = "Facebook",
        loginUrl = "https://m.facebook.com/login/",
        cookieDomains = listOf("https://m.facebook.com", "https://www.facebook.com", "https://facebook.com"),
    ),
)

object NetscapeCookieFormatter {
    fun buildNetscapeLines(domainToRawCookieHeader: Map<String, String>): List<String> {
        val seen = LinkedHashSet<String>()
        val lines = mutableListOf<String>()
        val expiry = (System.currentTimeMillis() / 1000L) + 31_536_000L // +1 year

        for ((rawUrl, header) in domainToRawCookieHeader) {
            if (header.isBlank()) continue
            val host = rawUrl
                .removePrefix("https://")
                .removePrefix("http://")
                .substringBefore("/")
                .trim()
            if (host.isEmpty()) continue
            val rootDomain = extractCookieDomain(host)

            header.split(";").forEach { pair ->
                val idx = pair.indexOf('=')
                if (idx <= 0) return@forEach
                val name = pair.substring(0, idx).trim()
                val value = pair.substring(idx + 1).trim()
                if (name.isEmpty()) return@forEach

                val key = "$rootDomain|$name"
                if (seen.add(key)) {
                    // Netscape format: domain  includeSubdomains  path  secure  expiry  name  value
                    lines.add("$rootDomain\tTRUE\t/\tTRUE\t$expiry\t$name\t$value")
                }
            }
        }
        return lines
    }

    private fun extractCookieDomain(host: String): String {
        val parts = host.split('.').filter { it.isNotBlank() }
        return if (parts.size >= 2) {
            ".${parts[parts.size - 2]}.${parts[parts.size - 1]}"
        } else {
            host
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebViewCookieLoginDialog(
    onDismiss: () -> Unit,
    onCookiesSaved: (netscapeLines: List<String>, siteLabel: String) -> Unit,
) {
    var selectedSite by remember { mutableStateOf(LoginSitePresets.first()) }
    var loadProgress by remember { mutableIntStateOf(0) }
    var webViewRef by remember { mutableStateOf<WebView?>(null) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = BgDark,
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Top bar
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(SurfaceCard)
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onDismiss) {
                            Icon(Icons.Default.Close, contentDescription = "Close", tint = TextSecondary)
                        }
                        Column {
                            Text(
                                text = "Sign In & Save Cookies",
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 15.sp,
                            )
                            Text(
                                text = "Sign in below, then tap Save Cookies",
                                color = TextSecondary,
                                fontSize = 11.sp,
                            )
                        }
                    }

                    Button(
                        onClick = {
                            val cm = CookieManager.getInstance()
                            cm.flush()
                            val cookieMap = linkedMapOf<String, String>()
                            selectedSite.cookieDomains.forEach { domainUrl ->
                                val raw = cm.getCookie(domainUrl)
                                if (!raw.isNullOrBlank()) {
                                    cookieMap[domainUrl] = raw
                                }
                            }
                            val currentUrl = webViewRef?.url
                            if (!currentUrl.isNullOrBlank()) {
                                val raw = cm.getCookie(currentUrl)
                                if (!raw.isNullOrBlank()) {
                                    cookieMap[currentUrl] = raw
                                }
                            }
                            val lines = NetscapeCookieFormatter.buildNetscapeLines(cookieMap)
                            onCookiesSaved(lines, selectedSite.label)
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = AccentIndigo),
                    ) {
                        Text("Save Cookies", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    }
                }

                // Site selector chips
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(BgDark)
                        .horizontalScroll(rememberScrollState())
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    LoginSitePresets.forEach { preset ->
                        FilterChip(
                            selected = selectedSite == preset,
                            onClick = {
                                selectedSite = preset
                                webViewRef?.loadUrl(preset.loginUrl)
                            },
                            label = { Text(preset.label, fontSize = 12.sp) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = AccentIndigo,
                                selectedLabelColor = Color.White,
                                containerColor = SurfaceCard,
                                labelColor = TextSecondary,
                            ),
                        )
                    }
                }

                if (loadProgress in 1..99) {
                    LinearProgressIndicator(
                        progress = { loadProgress / 100f },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(3.dp),
                        color = AccentSky,
                        trackColor = BorderSubtle,
                    )
                }

                // Embedded WebView
                AndroidView(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    factory = { ctx ->
                        WebView(ctx).apply {
                            val cm = CookieManager.getInstance()
                            cm.setAcceptCookie(true)
                            cm.setAcceptThirdPartyCookies(this, true)

                            settings.javaScriptEnabled = true
                            settings.domStorageEnabled = true
                            settings.databaseEnabled = true
                            settings.useWideViewPort = true
                            settings.loadWithOverviewMode = true

                            webViewClient = WebViewClient()
                            webChromeClient = object : WebChromeClient() {
                                override fun onProgressChanged(view: WebView?, newProgress: Int) {
                                    loadProgress = newProgress
                                }
                            }
                            loadUrl(selectedSite.loginUrl)
                            webViewRef = this
                        }
                    },
                )
            }
        }
    }
}
