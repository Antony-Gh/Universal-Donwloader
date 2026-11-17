package com.universaldownloader.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val BgDark = Color(0xFF0E0E12)
val SurfaceCard = Color(0xFF1E1E24)
val SurfaceCardAlt = Color(0xFF181820)
val TerminalBg = Color(0xFF090A0F)
val BorderSubtle = Color(0xFF27272A)
val AccentIndigo = Color(0xFF6366F1)
val AccentSky = Color(0xFF38BDF8)
val AccentBlue = Color(0xFF3B82F6)
val AccentMint = Color(0xFFA7F3D0)
val SuccessGreen = Color(0xFF10B981)
val WarningAmber = Color(0xFFF59E0B)
val ErrorRed = Color(0xFFEF4444)
val TextPrimary = Color(0xFFF4F4F8)
val TextSecondary = Color(0xFF9CA3AF)
val TextMuted = Color(0xFF64748B)

private val UniversalDarkColorScheme = darkColorScheme(
    primary = AccentIndigo,
    onPrimary = Color.White,
    secondary = AccentSky,
    onSecondary = Color(0xFF090A0F),
    tertiary = SuccessGreen,
    background = BgDark,
    onBackground = TextPrimary,
    surface = SurfaceCard,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceCardAlt,
    onSurfaceVariant = TextSecondary,
    outline = BorderSubtle,
    error = ErrorRed,
    onError = Color.White,
)

@Composable
fun UniversalDownloaderTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = UniversalDarkColorScheme,
        content = content,
    )
}
