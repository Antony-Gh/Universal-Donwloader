package com.universaldownloader.app.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.universaldownloader.app.model.HistoryEntry

class HistoryStore(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                platform TEXT NOT NULL,
                file_path TEXT NOT NULL,
                downloaded_at INTEGER NOT NULL
            )
            """.trimIndent()
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS download_history")
        onCreate(db)
    }

    fun record(url: String, title: String, platform: String, filePath: String) {
        val values = ContentValues().apply {
            put("url", url)
            put("title", title)
            put("platform", platform)
            put("file_path", filePath)
            put("downloaded_at", System.currentTimeMillis())
        }
        writableDatabase.insert("download_history", null, values)
    }

    fun query(search: String? = null, limit: Int = 100): List<HistoryEntry> {
        val results = mutableListOf<HistoryEntry>()
        val trimmed = search?.trim()
        val cursor = if (trimmed.isNullOrEmpty()) {
            readableDatabase.query(
                "download_history",
                null,
                null,
                null,
                null,
                null,
                "downloaded_at DESC",
                limit.toString(),
            )
        } else {
            val pattern = "%$trimmed%"
            readableDatabase.query(
                "download_history",
                null,
                "title LIKE ? OR platform LIKE ? OR url LIKE ?",
                arrayOf(pattern, pattern, pattern),
                null,
                null,
                "downloaded_at DESC",
                limit.toString(),
            )
        }

        cursor.use { c ->
            val idIdx = c.getColumnIndexOrThrow("id")
            val urlIdx = c.getColumnIndexOrThrow("url")
            val titleIdx = c.getColumnIndexOrThrow("title")
            val platformIdx = c.getColumnIndexOrThrow("platform")
            val fileIdx = c.getColumnIndexOrThrow("file_path")
            val timeIdx = c.getColumnIndexOrThrow("downloaded_at")

            while (c.moveToNext()) {
                results.add(
                    HistoryEntry(
                        id = c.getLong(idIdx),
                        url = c.getString(urlIdx),
                        title = c.getString(titleIdx),
                        platform = c.getString(platformIdx),
                        filePath = c.getString(fileIdx),
                        downloadedAt = c.getLong(timeIdx),
                    )
                )
            }
        }
        return results
    }

    fun clearAll() {
        writableDatabase.delete("download_history", null, null)
    }

    companion object {
        private const val DB_NAME = "universal_downloader_history.db"
        private const val DB_VERSION = 1
    }
}
