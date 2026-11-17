package com.universaldownloader.app.service

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.universaldownloader.app.MainActivity
import com.universaldownloader.app.R
import com.universaldownloader.app.UniversalDownloaderApp

class DownloadForegroundService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val title = intent.getStringExtra(EXTRA_TITLE) ?: "Starting download..."
                val notification = buildNotification(title, -1, indeterminate = true)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    startForeground(
                        NOTIFICATION_ID,
                        notification,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
                    )
                } else {
                    startForeground(NOTIFICATION_ID, notification)
                }
            }

            ACTION_PROGRESS -> {
                val title = intent.getStringExtra(EXTRA_TITLE) ?: "Downloading..."
                val progress = intent.getIntExtra(EXTRA_PROGRESS, 0)
                val indeterminate = intent.getBooleanExtra(EXTRA_INDETERMINATE, false)
                val manager = getSystemService(NotificationManager::class.java)
                manager.notify(NOTIFICATION_ID, buildNotification(title, progress, indeterminate))
            }

            ACTION_STOP -> {
                val finalMessage = intent.getStringExtra(EXTRA_TITLE)
                if (!finalMessage.isNullOrBlank()) {
                    val manager = getSystemService(NotificationManager::class.java)
                    manager.notify(COMPLETION_NOTIFICATION_ID, buildCompletionNotification(finalMessage))
                }
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun buildNotification(title: String, progress: Int, indeterminate: Boolean): Notification {
        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, UniversalDownloaderApp.CHANNEL_DOWNLOADS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Universal Downloader")
            .setContentText(title)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(pendingIntent)
            .setProgress(100, progress.coerceIn(0, 100), indeterminate)
            .build()
    }

    private fun buildCompletionNotification(message: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            1,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, UniversalDownloaderApp.CHANNEL_DOWNLOADS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Universal Downloader")
            .setContentText(message)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()
    }

    companion object {
        private const val NOTIFICATION_ID = 1001
        private const val COMPLETION_NOTIFICATION_ID = 1002
        const val ACTION_START = "com.universaldownloader.app.ACTION_START"
        const val ACTION_PROGRESS = "com.universaldownloader.app.ACTION_PROGRESS"
        const val ACTION_STOP = "com.universaldownloader.app.ACTION_STOP"
        const val EXTRA_TITLE = "extra_title"
        const val EXTRA_PROGRESS = "extra_progress"
        const val EXTRA_INDETERMINATE = "extra_indeterminate"

        fun start(context: Context, title: String) {
            try {
                val intent = Intent(context, DownloadForegroundService::class.java).apply {
                    action = ACTION_START
                    putExtra(EXTRA_TITLE, title)
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } catch (_: Exception) {
            }
        }

        fun updateProgress(context: Context, title: String, progress: Int, indeterminate: Boolean = false) {
            try {
                val intent = Intent(context, DownloadForegroundService::class.java).apply {
                    action = ACTION_PROGRESS
                    putExtra(EXTRA_TITLE, title)
                    putExtra(EXTRA_PROGRESS, progress)
                    putExtra(EXTRA_INDETERMINATE, indeterminate)
                }
                context.startService(intent)
            } catch (_: Exception) {
            }
        }

        fun stop(context: Context, completionMessage: String? = null) {
            try {
                val intent = Intent(context, DownloadForegroundService::class.java).apply {
                    action = ACTION_STOP
                    if (completionMessage != null) putExtra(EXTRA_TITLE, completionMessage)
                }
                context.startService(intent)
            } catch (_: Exception) {
            }
        }
    }
}
