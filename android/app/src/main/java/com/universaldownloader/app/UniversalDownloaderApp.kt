package com.universaldownloader.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.universaldownloader.app.data.HistoryStore
import com.universaldownloader.app.engine.DownloaderRepository

class UniversalDownloaderApp : Application() {

    lateinit var repository: DownloaderRepository
        private set

    lateinit var historyStore: HistoryStore
        private set

    override fun onCreate() {
        super.onCreate()
        repository = DownloaderRepository(this)
        historyStore = HistoryStore(this)
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_DOWNLOADS,
                getString(R.string.notification_channel_downloads),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = getString(R.string.notification_channel_downloads_desc)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_DOWNLOADS = "downloads_channel"
    }
}
