package com.quant.system.data.local

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.StockSelectionHistoryRecord
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalSerializationApi::class)
class SelectionHistoryDbHelper(context: Context) :
    SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE_SELECTION_HISTORY (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_key TEXT NOT NULL,
                strategy_label TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                created_at_millis INTEGER NOT NULL,
                created_at_label TEXT NOT NULL,
                candidates_json TEXT NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_selection_history_created_at ON $TABLE_SELECTION_HISTORY(created_at_millis DESC)",
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("DROP TABLE IF EXISTS $TABLE_SELECTION_HISTORY")
            onCreate(db)
        }
    }

    fun insertSelection(
        strategyKey: String,
        strategyLabel: String,
        candidates: List<Candidate>,
    ) {
        val now = System.currentTimeMillis()
        val createdAtLabel = formatMillis(now)
        val serializer = ListSerializer(Candidate.serializer())
        val candidatesJson = json.encodeToString(serializer, candidates)
        val values = ContentValues().apply {
            put("strategy_key", strategyKey)
            put("strategy_label", strategyLabel)
            put("candidate_count", candidates.size)
            put("created_at_millis", now)
            put("created_at_label", createdAtLabel)
            put("candidates_json", candidatesJson)
        }
        writableDatabase.insert(TABLE_SELECTION_HISTORY, null, values)
        trimToLimit(MAX_RECORDS)
    }

    fun loadRecent(limit: Int, strategyKey: String? = null): List<StockSelectionHistoryRecord> {
        val safeLimit = limit.coerceIn(1, 200)
        val where = strategyKey?.takeIf { it.isNotBlank() }?.let { "strategy_key=?" }
        val args = strategyKey?.takeIf { it.isNotBlank() }?.let { arrayOf(it) }
        val cursor = readableDatabase.query(
            TABLE_SELECTION_HISTORY,
            arrayOf(
                "id",
                "strategy_key",
                "strategy_label",
                "candidate_count",
                "created_at_millis",
                "created_at_label",
                "candidates_json",
            ),
            where,
            args,
            null,
            null,
            "created_at_millis DESC",
            safeLimit.toString(),
        )
        cursor.use { c ->
            val result = mutableListOf<StockSelectionHistoryRecord>()
            while (c.moveToNext()) {
                val candidatesJson = c.getString(6).orEmpty()
                val candidates = decodeCandidates(candidatesJson)
                result += StockSelectionHistoryRecord(
                    id = c.getLong(0),
                    strategyKey = c.getString(1).orEmpty(),
                    strategyLabel = c.getString(2).orEmpty(),
                    candidateCount = c.getInt(3),
                    createdAtMillis = c.getLong(4),
                    createdAtLabel = c.getString(5).orEmpty(),
                    topSymbols = candidates.mapNotNull { it.symbol }.take(6),
                    candidates = candidates,
                )
            }
            return result
        }
    }

    fun latestWithCandidates(): StockSelectionHistoryRecord? {
        return loadRecent(limit = 30).firstOrNull { it.candidates.isNotEmpty() }
    }

    fun deleteById(id: Long): Boolean {
        return writableDatabase.delete(
            TABLE_SELECTION_HISTORY,
            "id=?",
            arrayOf(id.toString()),
        ) > 0
    }

    fun clearAll(): Int {
        return writableDatabase.delete(TABLE_SELECTION_HISTORY, null, null)
    }

    private fun trimToLimit(maxSize: Int) {
        val db = writableDatabase
        db.execSQL(
            """
            DELETE FROM $TABLE_SELECTION_HISTORY
            WHERE id NOT IN (
                SELECT id FROM $TABLE_SELECTION_HISTORY
                ORDER BY created_at_millis DESC
                LIMIT $maxSize
            )
            """.trimIndent(),
        )
    }

    private fun decodeCandidates(raw: String): List<Candidate> {
        if (raw.isBlank()) return emptyList()
        val serializer = ListSerializer(Candidate.serializer())
        return runCatching { json.decodeFromString(serializer, raw) }.getOrDefault(emptyList())
    }

    private fun formatMillis(millis: Long): String {
        return SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(millis))
    }

    private companion object {
        const val DB_NAME = "quant_mobile_local.db"
        const val DB_VERSION = 2
        const val TABLE_SELECTION_HISTORY = "selection_history"
        const val MAX_RECORDS = 120
    }
}
