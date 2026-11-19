package com.universaldownloader.app.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.universaldownloader.app.model.SubscriptionEntry

class SubscriptionStore(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                label TEXT,
                audio_only INTEGER NOT NULL DEFAULT 0,
                quality TEXT NOT NULL DEFAULT 'best',
                max_downloads INTEGER NOT NULL DEFAULT 5,
                created_at INTEGER NOT NULL,
                last_synced_at INTEGER
            )
            """.trimIndent()
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS subscriptions")
        onCreate(db)
    }

    fun addOrUpdate(
        url: String,
        label: String = "",
        audioOnly: Boolean = false,
        quality: String = "best",
        maxDownloads: Int = 5,
    ): SubscriptionEntry {
        val cleanUrl = url.trim()
        val now = System.currentTimeMillis()
        val values = ContentValues().apply {
            put("url", cleanUrl)
            put("label", label.trim())
            put("audio_only", if (audioOnly) 1 else 0)
            put("quality", quality.ifBlank { "best" })
            put("max_downloads", maxDownloads.coerceIn(1, 100))
            put("created_at", now)
        }

        val rowId = writableDatabase.insertWithOnConflict(
            "subscriptions",
            null,
            values,
            SQLiteDatabase.CONFLICT_REPLACE,
        )

        return SubscriptionEntry(
            id = rowId,
            url = cleanUrl,
            label = label.trim(),
            audioOnly = audioOnly,
            quality = quality.ifBlank { "best" },
            maxDownloads = maxDownloads.coerceIn(1, 100),
            createdAt = now,
        )
    }

    fun remove(id: Long): Boolean {
        val count = writableDatabase.delete("subscriptions", "id = ?", arrayOf(id.toString()))
        return count > 0
    }

    fun removeByUrl(url: String): Boolean {
        val count = writableDatabase.delete("subscriptions", "url = ?", arrayOf(url.trim()))
        return count > 0
    }

    fun updateLastSynced(id: Long, timestamp: Long = System.currentTimeMillis()) {
        val values = ContentValues().apply {
            put("last_synced_at", timestamp)
        }
        writableDatabase.update("subscriptions", values, "id = ?", arrayOf(id.toString()))
    }

    fun list(): List<SubscriptionEntry> {
        val results = mutableListOf<SubscriptionEntry>()
        val cursor = readableDatabase.query(
            "subscriptions",
            null,
            null,
            null,
            null,
            null,
            "id ASC",
        )

        cursor.use { c ->
            val idIdx = c.getColumnIndexOrThrow("id")
            val urlIdx = c.getColumnIndexOrThrow("url")
            val labelIdx = c.getColumnIndexOrThrow("label")
            val audioIdx = c.getColumnIndexOrThrow("audio_only")
            val qualityIdx = c.getColumnIndexOrThrow("quality")
            val maxIdx = c.getColumnIndexOrThrow("max_downloads")
            val createdIdx = c.getColumnIndexOrThrow("created_at")
            val syncedIdx = c.getColumnIndexOrThrow("last_synced_at")

            while (c.moveToNext()) {
                val syncedVal = if (c.isNull(syncedIdx)) null else c.getLong(syncedIdx)
                results.add(
                    SubscriptionEntry(
                        id = c.getLong(idIdx),
                        url = c.getString(urlIdx),
                        label = c.getString(labelIdx) ?: "",
                        audioOnly = c.getInt(audioIdx) == 1,
                        quality = c.getString(qualityIdx) ?: "best",
                        maxDownloads = c.getInt(maxIdx),
                        createdAt = c.getLong(createdIdx),
                        lastSyncedAt = syncedVal,
                    )
                )
            }
        }
        return results
    }

    companion object {
        private const val DB_NAME = "universal_downloader_subscriptions.db"
        private const val DB_VERSION = 1
    }
}
