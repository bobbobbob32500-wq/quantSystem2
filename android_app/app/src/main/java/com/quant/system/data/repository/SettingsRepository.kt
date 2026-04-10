package com.quant.system.data.repository

import android.content.Context
import com.quant.system.data.api.RetrofitClient
import com.quant.system.data.model.ManualTradeRecord
import com.quant.system.data.model.TradeReminderSetting
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class SettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }

    fun getBaseUrl(): String {
        return prefs.getString(KEY_BASE_URL, RetrofitClient.defaultBaseUrl)
            ?.takeIf { it.isNotBlank() }
            ?: RetrofitClient.defaultBaseUrl
    }

    fun saveBaseUrl(baseUrl: String) {
        prefs.edit()
            .putString(KEY_BASE_URL, RetrofitClient.normalizeBaseUrl(baseUrl))
            .apply()
    }

    fun isHighContrastEnabled(): Boolean = prefs.getBoolean(KEY_HIGH_CONTRAST, false)

    fun setHighContrastEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_HIGH_CONTRAST, enabled).apply()
    }

    fun getDefaultStrategy(): String {
        return prefs.getString(KEY_DEFAULT_STRATEGY, "secondary_launch")
            ?.takeIf { it.isNotBlank() }
            ?: "secondary_launch"
    }

    fun setDefaultStrategy(strategy: String) {
        prefs.edit()
            .putString(KEY_DEFAULT_STRATEGY, strategy.trim().ifBlank { "secondary_launch" })
            .apply()
    }

    fun getHomeModuleOrder(): String {
        return prefs.getString(KEY_HOME_MODULE_ORDER, "overview,task,health,metrics,signals")
            ?.takeIf { it.isNotBlank() }
            ?: "overview,task,health,metrics,signals"
    }

    fun setHomeModuleOrder(order: String) {
        prefs.edit()
            .putString(KEY_HOME_MODULE_ORDER, order.trim().ifBlank { "overview,task,health,metrics,signals" })
            .apply()
    }

    fun isHighPrioritySignalOnlyEnabled(): Boolean = prefs.getBoolean(KEY_NOTIFY_HIGH_PRIORITY_ONLY, false)

    fun setHighPrioritySignalOnlyEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_NOTIFY_HIGH_PRIORITY_ONLY, enabled).apply()
    }

    fun isActionCompleteNotifyEnabled(): Boolean = prefs.getBoolean(KEY_NOTIFY_ACTION_COMPLETE, true)

    fun setActionCompleteNotifyEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_NOTIFY_ACTION_COMPLETE, enabled).apply()
    }

    fun getSilentStart(): String = prefs.getString(KEY_NOTIFY_SILENT_START, "22:30").orEmpty().ifBlank { "22:30" }

    fun setSilentStart(value: String) {
        prefs.edit().putString(KEY_NOTIFY_SILENT_START, value.trim().ifBlank { "22:30" }).apply()
    }

    fun getSilentEnd(): String = prefs.getString(KEY_NOTIFY_SILENT_END, "07:30").orEmpty().ifBlank { "07:30" }

    fun setSilentEnd(value: String) {
        prefs.edit().putString(KEY_NOTIFY_SILENT_END, value.trim().ifBlank { "07:30" }).apply()
    }

    fun getTradeNote(tradeId: String): String {
        if (tradeId.isBlank()) return ""
        return prefs.getString("$KEY_TRADE_NOTE_PREFIX$tradeId", "").orEmpty()
    }

    fun setTradeNote(tradeId: String, note: String) {
        if (tradeId.isBlank()) return
        prefs.edit().putString("$KEY_TRADE_NOTE_PREFIX$tradeId", note).apply()
    }

    fun getTradeReminder(tradeId: String): TradeReminderSetting {
        if (tradeId.isBlank()) return TradeReminderSetting()
        val raw = prefs.getString("$KEY_TRADE_REMINDER_PREFIX$tradeId", "").orEmpty()
        return runCatching { json.decodeFromString<TradeReminderSetting>(raw) }.getOrDefault(TradeReminderSetting())
    }

    fun setTradeReminder(tradeId: String, setting: TradeReminderSetting) {
        if (tradeId.isBlank()) return
        prefs.edit().putString("$KEY_TRADE_REMINDER_PREFIX$tradeId", json.encodeToString(setting)).apply()
    }

    fun getManualTradeRecords(limit: Int = 80): List<ManualTradeRecord> {
        val raw = prefs.getString(KEY_MANUAL_TRADE_RECORDS, "").orEmpty()
        val records = runCatching { json.decodeFromString<List<ManualTradeRecord>>(raw) }.getOrDefault(emptyList())
        return records.take(limit)
    }

    fun appendManualTradeRecord(record: ManualTradeRecord, maxSize: Int = 200) {
        val existing = getManualTradeRecords(limit = maxSize)
        val merged = listOf(record) + existing
        prefs.edit().putString(KEY_MANUAL_TRADE_RECORDS, json.encodeToString(merged.take(maxSize))).apply()
    }

    fun getSignalPriorityKeywords(): String {
        return prefs.getString(KEY_SIGNAL_PRIORITY_KEYWORDS, DEFAULT_SIGNAL_PRIORITY_KEYWORDS)
            .orEmpty()
            .ifBlank { DEFAULT_SIGNAL_PRIORITY_KEYWORDS }
    }

    fun setSignalPriorityKeywords(value: String) {
        prefs.edit()
            .putString(KEY_SIGNAL_PRIORITY_KEYWORDS, value.trim().ifBlank { DEFAULT_SIGNAL_PRIORITY_KEYWORDS })
            .apply()
    }

    fun getNotificationLogRetentionDays(): Int {
        val value = prefs.getInt(KEY_NOTIFICATION_LOG_RETENTION_DAYS, DEFAULT_NOTIFICATION_LOG_RETENTION_DAYS)
        return value.coerceIn(1, 30)
    }

    fun setNotificationLogRetentionDays(days: Int) {
        prefs.edit()
            .putInt(KEY_NOTIFICATION_LOG_RETENTION_DAYS, days.coerceIn(1, 30))
            .apply()
    }

    fun getNotificationLogs(limit: Int = 120): List<String> {
        val retentionDays = getNotificationLogRetentionDays()
        val raw = prefs.getString(KEY_NOTIFICATION_LOGS, "").orEmpty()
        val logs = runCatching { json.decodeFromString<List<String>>(raw) }.getOrDefault(emptyList())
        val retained = retainByDays(logs, retentionDays)
        if (retained.size != logs.size) {
            prefs.edit().putString(KEY_NOTIFICATION_LOGS, json.encodeToString(retained)).apply()
        }
        return retained.take(limit)
    }

    fun appendNotificationLog(entry: String, maxSize: Int = 300) {
        val normalized = entry.trim()
        if (normalized.isBlank()) return
        val existing = getNotificationLogs(limit = maxSize)
        val stamped = "${System.currentTimeMillis()}|$normalized"
        val merged = listOf(stamped) + existing
        prefs.edit().putString(KEY_NOTIFICATION_LOGS, json.encodeToString(merged.take(maxSize))).apply()
    }

    fun clearNotificationLogs() {
        prefs.edit().putString(KEY_NOTIFICATION_LOGS, "[]").apply()
    }

    private fun retainByDays(logs: List<String>, days: Int): List<String> {
        val threshold = System.currentTimeMillis() - days * 24L * 60L * 60L * 1000L
        return logs.filter { line ->
            val prefix = line.substringBefore("|", missingDelimiterValue = "")
            val timestamp = prefix.toLongOrNull() ?: return@filter true
            timestamp >= threshold
        }
    }

    private companion object {
        const val PREFS_NAME = "quant_mobile_settings"
        const val KEY_BASE_URL = "base_url"
        const val KEY_HIGH_CONTRAST = "high_contrast_enabled"
        const val KEY_DEFAULT_STRATEGY = "default_strategy"
        const val KEY_HOME_MODULE_ORDER = "home_module_order"
        const val KEY_NOTIFY_HIGH_PRIORITY_ONLY = "notify_high_priority_only"
        const val KEY_NOTIFY_ACTION_COMPLETE = "notify_action_complete"
        const val KEY_NOTIFY_SILENT_START = "notify_silent_start"
        const val KEY_NOTIFY_SILENT_END = "notify_silent_end"
        const val KEY_MANUAL_TRADE_RECORDS = "manual_trade_records"
        const val KEY_SIGNAL_PRIORITY_KEYWORDS = "signal_priority_keywords"
        const val KEY_NOTIFICATION_LOGS = "notification_logs"
        const val KEY_NOTIFICATION_LOG_RETENTION_DAYS = "notification_log_retention_days"
        const val KEY_TRADE_NOTE_PREFIX = "trade_note_"
        const val KEY_TRADE_REMINDER_PREFIX = "trade_reminder_"
        const val DEFAULT_SIGNAL_PRIORITY_KEYWORDS = "buy,strong,breakout,突破,高优先"
        const val DEFAULT_NOTIFICATION_LOG_RETENTION_DAYS = 7
    }
}
