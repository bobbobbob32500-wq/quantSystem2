package com.quant.system.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// AI服务状态
@Serializable
data class AIStatus(
    val enabled: Boolean,
    val available: Boolean,
    @SerialName("llm_status")
    val llmStatus: LLMStatus? = null,
)

@Serializable
data class LLMStatus(
    val available: Boolean,
    @SerialName("base_url")
    val baseUrl: String,
    @SerialName("default_model")
    val defaultModel: String,
    @SerialName("code_model")
    val codeModel: String,
    @SerialName("installed_models")
    val installedModels: List<String>,
)

// AI对话请求
@Serializable
data class AIChatRequest(
    val message: String,
    val context: Map<String, String>? = null,
)

// AI对话响应
@Serializable
data class AIChatResponse(
    val success: Boolean,
    val response: String? = null,
    val message: String? = null,
)

// 快速问答请求
@Serializable
data class AIQuickAskRequest(
    val key: String,
)

// 管家状态
@Serializable
data class ButlerStatus(
    val running: Boolean,
    @SerialName("llm_available")
    val llmAvailable: Boolean,
    @SerialName("last_briefing_time")
    val lastBriefingTime: String? = null,
    @SerialName("last_review_time")
    val lastReviewTime: String? = null,
    @SerialName("active_alerts_count")
    val activeAlertsCount: Int,
    @SerialName("active_alerts")
    val activeAlerts: List<ButlerAlert>,
)

@Serializable
data class ButlerAlert(
    val level: String,
    val type: String,
    val message: String,
)

// 盘前简报请求
@Serializable
data class AIBriefingRequest(
    @SerialName("yesterday_review")
    val yesterdayReview: Map<String, String>? = null,
    @SerialName("today_selection")
    val todaySelection: List<Map<String, String>>? = null,
    @SerialName("overnight_news")
    val overnightNews: List<Map<String, String>>? = null,
    @SerialName("data_status")
    val dataStatus: Map<String, String>? = null,
)

// 盘前简报结果
@Serializable
data class AIBriefingResult(
    val briefing: String,
    @SerialName("focus_stocks")
    val focusStocks: List<FocusStock>,
    @SerialName("risk_alerts")
    val riskAlerts: List<RiskAlert>,
    @SerialName("opportunity_alerts")
    val opportunityAlerts: List<OpportunityAlert>,
    val suggestions: List<String>,
)

@Serializable
data class FocusStock(
    val code: String,
    val name: String,
    val score: Double? = null,
)

@Serializable
data class RiskAlert(
    val type: String,
    val source: String? = null,
)

@Serializable
data class OpportunityAlert(
    val type: String,
    val stock: String? = null,
)

// 盘中监控请求
@Serializable
data class AIMonitorRequest(
    val holdings: List<Map<String, String>>? = null,
    val signals: List<Map<String, String>>? = null,
    @SerialName("market_status")
    val marketStatus: Map<String, String>? = null,
)

// 盘中监控结果
@Serializable
data class AIMonitorResult(
    @SerialName("status_summary")
    val statusSummary: String,
    val alerts: List<ButlerAlert>,
    @SerialName("action_suggestions")
    val actionSuggestions: List<String>,
    @SerialName("watch_reminders")
    val watchReminders: List<WatchReminder>,
)

@Serializable
data class WatchReminder(
    val stock: String,
    val reminder: String,
)

// 盘后复盘请求
@Serializable
data class AIReviewRequest(
    @SerialName("today_trades")
    val todayTrades: List<Map<String, String>>? = null,
    @SerialName("today_signals")
    val todaySignals: List<Map<String, String>>? = null,
    val holdings: List<Map<String, String>>? = null,
    @SerialName("market_summary")
    val marketSummary: Map<String, String>? = null,
)

// 盘后复盘结果
@Serializable
data class AIReviewResult(
    @SerialName("review_report")
    val reviewReport: String,
    @SerialName("performance_summary")
    val performanceSummary: String,
    val lessons: List<String>,
    @SerialName("tomorrow_plan")
    val tomorrowPlan: String,
)

// 风险检查请求
@Serializable
data class AIRiskCheckRequest(
    val holdings: List<Map<String, String>> = emptyList(),
    @SerialName("market_data")
    val marketData: Map<String, String> = emptyMap(),
)

// 风险检查结果
@Serializable
data class AIRiskCheckResult(
    @SerialName("risk_level")
    val riskLevel: String,
    val alerts: List<ButlerAlert>,
    val suggestions: List<String>,
)

// 信号分析请求
@Serializable
data class AISignalAnalysisRequest(
    val signal: Map<String, String>,
    @SerialName("stock_info")
    val stockInfo: Map<String, String>,
    val position: Map<String, String>? = null,
)

// 信号分析结果
@Serializable
data class AISignalAnalysisResult(
    val analysis: String,
    val action: String,
    val confidence: Double,
    val reason: String,
    @SerialName("execution_advice")
    val executionAdvice: String,
)

// 通用AI响应包装
@Serializable
data class AIResultResponse<T>(
    val success: Boolean,
    val result: T? = null,
    val message: String? = null,
)
