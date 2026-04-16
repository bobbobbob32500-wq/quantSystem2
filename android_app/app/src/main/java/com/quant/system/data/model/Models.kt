package com.quant.system.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable
data class ApiResponse<T>(
    val success: Boolean,
    val data: T? = null,
    val detail: String? = null,
    /** 部分接口将提示信息放在顶层 message 字段（与 data 并列） */
    val message: String? = null,
)

@Serializable
data class RootResponse(
    val message: String,
    val version: String,
    val docs: String,
)

@Serializable
data class HealthResponse(
    val status: String,
    val service: String,
)

@Serializable
data class DashboardSnapshot(
    val meta: Meta? = null,
    val overview: Overview? = null,
    @SerialName("today_board")
    val todayBoard: TodayBoard? = null,
    @SerialName("monitor_session")
    val monitorSession: MonitorSession? = null,
    @SerialName("candidate_pool")
    val candidatePool: CandidatePool? = null,
    @SerialName("virtual_trades")
    val virtualTrades: VirtualTrades? = null,
    val signals: Signals? = null,
    val health: Health? = null,
    val recommendations: Recommendations? = null,
)

@Serializable
data class Meta(
    @SerialName("generated_at")
    val generatedAt: String? = null,
    @SerialName("generated_label")
    val generatedLabel: String? = null,
    @SerialName("app_name")
    val appName: String? = null,
    val version: String? = null,
    @SerialName("market_session")
    val marketSession: MarketSession? = null,
)

@Serializable
data class MarketSession(
    val phase: String? = null,
    val detail: String? = null,
    val clock: String? = null,
    val weekday: Int? = null,
)

@Serializable
data class Overview(
    val headline: Headline? = null,
    val metrics: List<Metric> = emptyList(),
)

@Serializable
data class Headline(
    @SerialName("health_status")
    val healthStatus: String? = null,
    @SerialName("health_label")
    val healthLabel: String? = null,
    @SerialName("candidate_status")
    val candidateStatus: String? = null,
    @SerialName("last_signal_label")
    val lastSignalLabel: String? = null,
    @SerialName("recommendation_status")
    val recommendationStatus: String? = null,
)

@Serializable
data class Metric(
    val key: String? = null,
    val label: String? = null,
    val value: JsonElement? = null,
    val unit: String? = null,
    val note: String? = null,
    val tone: String? = null,
)

@Serializable
data class CandidatePool(
    val count: Int? = null,
    @SerialName("avg_score")
    val avgScore: Double? = null,
    @SerialName("freshness_label")
    val freshnessLabel: String? = null,
    @SerialName("top_candidates")
    val topCandidates: List<Candidate> = emptyList(),
)

@Serializable
data class Candidate(
    val symbol: String? = null,
    val name: String? = null,
    val score: Double? = null,
    @SerialName("strategy_profile")
    val strategyProfile: String? = null,
    @SerialName("trigger_reason")
    val triggerReason: String? = null,
    @SerialName("strategy_name")
    val strategyName: String? = null,
    @SerialName("pct_chg")
    val pctChg: Double? = null,
    @SerialName("quote_pct_change")
    val quotePctChange: Double? = null,
    @SerialName("trigger_price")
    val triggerPrice: Double? = null,
    @SerialName("entry_price")
    val entryPrice: Double? = null,
    @SerialName("stop_loss")
    val stopLoss: Double? = null,
    @SerialName("vol_ratio_5")
    val volRatio5: Double? = null,
    @SerialName("upper_shadow_pct")
    val upperShadowPct: Double? = null,
    @SerialName("current_price")
    val currentPrice: Double? = null,
    @SerialName("last_price")
    val lastPrice: Double? = null,
    val close: Double? = null,
)

@Serializable
data class MonitorSession(
    @SerialName("is_active")
    val isActive: Boolean = false,
    @SerialName("status_label")
    val statusLabel: String? = null,
    @SerialName("runtime_usable")
    val runtimeUsable: Boolean = false,
    @SerialName("runtime_status_label")
    val runtimeStatusLabel: String? = null,
    @SerialName("display_text")
    val displayText: String? = null,
    @SerialName("last_refresh_at")
    val lastRefreshAt: String? = null,
)

@Serializable
data class TodayBoard(
    val status: String? = null,
    val tone: String? = null,
    val action: String? = null,
    val reason: String? = null,
    val cards: List<TodayBoardCard> = emptyList(),
    @SerialName("quick_actions")
    val quickActions: List<TodayQuickAction> = emptyList(),
    val highlights: List<String> = emptyList(),
)

@Serializable
data class TodayBoardCard(
    val label: String? = null,
    val value: String? = null,
    val note: String? = null,
    val tone: String? = null,
)

@Serializable
data class TodayQuickAction(
    val key: String? = null,
    val label: String? = null,
    val hint: String? = null,
)

@Serializable
data class VirtualTrades(
    @SerialName("open_count")
    val openCount: Int? = null,
    @SerialName("closed_count")
    val closedCount: Int? = null,
    val stats: TradeStats? = null,
    @SerialName("open_trades")
    val openTrades: List<Trade> = emptyList(),
)

@Serializable
data class TradeStats(
    @SerialName("total_signals")
    val totalSignals: Int? = null,
    @SerialName("win_rate_pct")
    val winRatePct: Double? = null,
)

@Serializable
data class Trade(
    @SerialName("trade_id")
    val tradeId: String? = null,
    val symbol: String? = null,
    val name: String? = null,
    @SerialName("hold_price")
    val holdPrice: Double? = null,
    @SerialName("current_price")
    val currentPrice: Double? = null,
    @SerialName("profit_pct")
    val profitPct: Double? = null,
    @SerialName("buy_price")
    val buyPrice: Double? = null,
    @SerialName("last_price")
    val lastPrice: Double? = null,
    @SerialName("last_pnl_pct")
    val lastPnlPct: Double? = null,
    @SerialName("buy_time")
    val buyTime: String? = null,
    @SerialName("last_trade_date")
    val lastTradeDate: String? = null,
    @SerialName("price_source")
    val priceSource: String? = null,
    @SerialName("quote_pct_change")
    val quotePctChange: Double? = null,
    @SerialName("quote_time")
    val quoteTime: String? = null,
)

@Serializable
data class VirtualTradeUpsertRequest(
    val symbol: String,
    val name: String,
    @SerialName("buy_price")
    val buyPrice: Double,
    val quantity: Int = 0,
    @SerialName("buy_time")
    val buyTime: String? = null,
)

@Serializable
data class Signals(
    @SerialName("recent_count")
    val recentCount: Int? = null,
    @SerialName("latest_signal_label")
    val latestSignalLabel: String? = null,
    @SerialName("latest_items")
    val latestItems: List<SignalItem> = emptyList(),
)

@Serializable
data class SignalItem(
    @SerialName("ts_code")
    val tsCode: String? = null,
    val name: String? = null,
    @SerialName("signal_type")
    val signalType: String? = null,
    @SerialName("signal_time")
    val signalTime: String? = null,
    @SerialName("trigger_reason")
    val triggerReason: String? = null,
    val suggestion: String? = null,
)

@Serializable
data class Health(
    val status: String? = null,
    @SerialName("status_label")
    val statusLabel: String? = null,
    val subtitle: String? = null,
    val tone: String? = null,
)

@Serializable
data class Recommendations(
    @SerialName("daily_count")
    val dailyCount: Int? = null,
    @SerialName("latest_date_label")
    val latestDateLabel: String? = null,
)

@Serializable
data class ActionRequest(
    val action: String,
    val payload: JsonObject? = null,
    val confirmed: Boolean = false,
)

@Serializable
data class ActionResponse(
    val success: Boolean,
    val action: String? = null,
    @SerialName("task_id")
    val taskId: String? = null,
    val message: String? = null,
    val payload: JsonObject? = null,
)

@Serializable
data class ActionRecord(
    @SerialName("action_key")
    val actionKey: String,
    val status: String,
    val message: String? = null,
    val payload: JsonObject? = null,
    @SerialName("created_time")
    val createdTime: String,
)

@Serializable
data class BackgroundTaskRecord(
    @SerialName("task_id")
    val taskId: String,
    @SerialName("action_key")
    val actionKey: String? = null,
    @SerialName("action_label")
    val actionLabel: String? = null,
    val status: String? = null,
    val message: String? = null,
    @SerialName("started_at")
    val startedAt: String? = null,
    @SerialName("updated_at")
    val updatedAt: String? = null,
    @SerialName("ended_at")
    val endedAt: String? = null,
    @SerialName("retryable")
    val retryable: Boolean = false,
    @SerialName("progress_pct")
    val progressPct: Int? = null,
    @SerialName("error_code")
    val errorCode: String? = null,
    val payload: JsonObject? = null,
)

@Serializable
data class StrategyMeta(
    val id: String,
    val name: String,
    val description: String? = null,
    val scene: String? = null,
    @SerialName("default_params")
    val defaultParams: JsonObject? = null,
)

@Serializable
data class StockDetailPayload(
    val symbol: String,
    val name: String? = null,
    @SerialName("strategy_tags")
    val strategyTags: List<String> = emptyList(),
    @SerialName("selection_reason")
    val selectionReason: String? = null,
    @SerialName("market_phase")
    val marketPhase: String? = null,
    @SerialName("key_risks")
    val keyRisks: List<String> = emptyList(),
    @SerialName("todo_actions")
    val todoActions: List<String> = emptyList(),
    val candidate: JsonObject? = null,
    @SerialName("latest_signal")
    val latestSignal: JsonObject? = null,
    @SerialName("signal_timeline")
    val signalTimeline: List<JsonObject> = emptyList(),
    @SerialName("open_trade")
    val openTrade: JsonObject? = null,
    @SerialName("risk_tags")
    val riskTags: List<String> = emptyList(),
    @SerialName("action_suggestion")
    val actionSuggestion: String? = null,
)

@Serializable
data class AnalyticsSummaryPayload(
    @SerialName("week_hit_rate")
    val weekHitRate: Double = 0.0,
    @SerialName("month_hit_rate")
    val monthHitRate: Double = 0.0,
    @SerialName("strategy_success_rate")
    val strategySuccessRate: Double = 0.0,
    @SerialName("return_summary")
    val returnSummary: JsonObject? = null,
    @SerialName("drawdown_summary")
    val drawdownSummary: JsonObject? = null,
    @SerialName("latest_recommendation_date")
    val latestRecommendationDate: String? = null,
)

@Serializable
data class WatchlistPayload(
    val symbols: List<String> = emptyList(),
    @SerialName("updated_at")
    val updatedAt: String? = null,
)

@Serializable
data class TradeReminderSetting(
    val stopLossPct: Double? = null,
    val takeProfitPct: Double? = null,
)

@Serializable
data class ManualTradeRecord(
    val symbol: String,
    val name: String,
    val action: String,
    val price: Double,
    val quantity: Int,
    @SerialName("executed_at")
    val executedAt: String,
    val note: String? = null,
)

@Serializable
data class AppUpdatePayload(
    val available: Boolean = false,
    val message: String? = null,
    @SerialName("latest_version_code")
    val latestVersionCode: Int? = null,
    @SerialName("latest_version_name")
    val latestVersionName: String? = null,
    @SerialName("apk_url")
    val apkUrl: String? = null,
    val changelog: String? = null,
    @SerialName("force_update")
    val forceUpdate: Boolean = false,
    @SerialName("published_at")
    val publishedAt: String? = null,
)
