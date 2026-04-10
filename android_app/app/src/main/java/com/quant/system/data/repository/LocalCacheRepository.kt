package com.quant.system.data.repository

import android.content.Context
import com.quant.system.data.model.ActionRecord
import com.quant.system.data.model.DashboardSnapshot
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

class LocalCacheRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }

    fun saveDashboardSnapshot(snapshot: DashboardSnapshot) {
        runCatching {
            val text = json.encodeToString(DashboardSnapshot.serializer(), snapshot)
            prefs.edit()
                .putString(KEY_DASHBOARD_SNAPSHOT, text)
                .putLong(KEY_DASHBOARD_CACHED_AT, System.currentTimeMillis())
                .apply()
        }
    }

    fun getDashboardSnapshot(): DashboardSnapshot? {
        val text = prefs.getString(KEY_DASHBOARD_SNAPSHOT, null) ?: return null
        return runCatching {
            json.decodeFromString(DashboardSnapshot.serializer(), text)
        }.getOrNull()
    }

    fun getDashboardCachedAt(): Long? {
        val value = prefs.getLong(KEY_DASHBOARD_CACHED_AT, 0L)
        return value.takeIf { it > 0L }
    }

    fun saveActionRecords(records: List<ActionRecord>) {
        runCatching {
            val serializer = ListSerializer(ActionRecord.serializer())
            val text = json.encodeToString(serializer, records)
            prefs.edit()
                .putString(KEY_ACTION_RECORDS, text)
                .putLong(KEY_ACTIONS_CACHED_AT, System.currentTimeMillis())
                .apply()
        }
    }

    fun getActionRecords(): List<ActionRecord> {
        val text = prefs.getString(KEY_ACTION_RECORDS, null) ?: return emptyList()
        return runCatching {
            val serializer = ListSerializer(ActionRecord.serializer())
            json.decodeFromString(serializer, text)
        }.getOrDefault(emptyList())
    }

    fun getActionRecordsCachedAt(): Long? {
        val value = prefs.getLong(KEY_ACTIONS_CACHED_AT, 0L)
        return value.takeIf { it > 0L }
    }

    private companion object {
        const val PREFS_NAME = "quant_mobile_cache"
        const val KEY_DASHBOARD_SNAPSHOT = "dashboard_snapshot"
        const val KEY_DASHBOARD_CACHED_AT = "dashboard_cached_at"
        const val KEY_ACTION_RECORDS = "action_records"
        const val KEY_ACTIONS_CACHED_AT = "actions_cached_at"
    }
}
