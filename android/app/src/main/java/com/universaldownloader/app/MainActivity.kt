package com.universaldownloader.app

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import com.universaldownloader.app.ui.screens.MainScreen
import com.universaldownloader.app.ui.theme.UniversalDownloaderTheme
import com.universaldownloader.app.viewmodel.MainViewModel

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* User decision handled silently */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        requestOptionalPermissions()
        handleIncomingIntent(intent)

        setContent {
            UniversalDownloaderTheme {
                MainScreen(viewModel = viewModel)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            try {
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val text = cm.primaryClip?.getItemAt(0)?.coerceToText(this)?.toString()
                if (!text.isNullOrBlank()) {
                    viewModel.onClipboardTextDetected(text)
                }
            } catch (_: Exception) {
            }
        }
    }

    private fun handleIncomingIntent(incomingIntent: Intent?) {
        if (incomingIntent == null) return

        when (incomingIntent.action) {
            Intent.ACTION_SEND -> {
                val text = incomingIntent.getStringExtra(Intent.EXTRA_TEXT)
                    ?: incomingIntent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                    ?: incomingIntent.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString()
                if (!text.isNullOrBlank()) {
                    viewModel.onSharedTextReceived(text)
                }
            }
            Intent.ACTION_VIEW -> {
                val dataUri = incomingIntent.dataString ?: incomingIntent.data?.toString()
                if (!dataUri.isNullOrBlank()) {
                    viewModel.onSharedTextReceived(dataUri)
                }
            }
        }
    }

    private fun requestOptionalPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
}
