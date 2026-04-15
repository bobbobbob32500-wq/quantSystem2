package com.quant.system.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// ==================== 预警系统模型 ====================

@Serializable
data class AlertItem(
    val id: String,
    val type: String,
    val level: String,
    val title: String,
    val message: String,
    val symbol: String = "",
    val action: String = "",
    val details: Map<String, String> = emptyMap(),
    @SerialName("created_at")
    val createdAt: String = "",
    val acked: Boolean = false,
)

@Serializable
data class AlertSummary(
    @SerialName("total_active")
    val totalActive: Int,
    @SerialName("total_history")
    val totalHistory: Int = 0,
    @SerialName("by_level")
    val byLevel: Map<String, Int> = emptyMap(),
    @SerialName("by_type")
    val byType: Map<String, Int> = emptyMap(),
    @SerialName("has_critical")
    val hasCritical: Boolean = false,
)

// ==================== 盯盘系统模型 ====================

@Serializable
data class PriceAlertItem(
    val id: String,
    val symbol: String,
    @SerialName("watch_type")
    val watchType: String,
    @SerialName("target_value")
    val targetValue: Double,
    val label: String = "",
    @SerialName("created_at")
    val createdAt: String = "",
    val triggered: Boolean = false,
    @SerialName("triggered_at")
    val triggeredAt: String? = null,
)

@Serializable
data class WatcherSummary(
    @SerialName("total_alerts")
    val totalAlerts: Int,
    @SerialName("active_alerts")
    val activeAlerts: Int,
    @SerialName("triggered_alerts")
    val triggeredAlerts: Int,
    @SerialName("recent_events")
    val recentEvents: Int,
)

// ==================== 策略优化模型 ====================

@Serializable
data class StrategyOptimizationResult(
    @SerialName("strategy_id")
    val strategyId: String,
    @SerialName("strategy_name")
    val strategyName: String,
    @SerialName("current_params")
    val currentParams: Map<String, String> = emptyMap(),
    @SerialName("suggested_params")
    val suggestedParams: Map<String, String> = emptyMap(),
    val reasons: List<String> = emptyList(),
    @SerialName("has_suggestions")
    val hasSuggestions: Boolean = false,
    @SerialName("analyzed_at")
    val analyzedAt: String = "",
)

@Serializable
data class MarketAdaptiveResult(
    @SerialName("market_regime")
    val marketRegime: String,
    @SerialName("regime_name")
    val regimeName: String,
    @SerialName("suggested_params")
    val suggestedParams: Map<String, String> = emptyMap(),
    @SerialName("changed_params")
    val changedParams: Map<String, String> = emptyMap(),
    val reason: String = "",
    @SerialName("has_changes")
    val hasChanges: Boolean = false,
)

// ==================== 执行计划模型 ====================

@Serializable
data class ExecutionPlan(
    val id: String,
    val action: String,
    val symbol: String,
    val name: String = "",
    @SerialName("total_position")
    val totalPosition: Double = 0.0,
    val batches: List<ExecutionBatch> = emptyList(),
    @SerialName("stop_loss")
    val stopLoss: Double = 0.0,
    @SerialName("take_profit")
    val takeProfit: List<Double> = emptyList(),
    val reason: String = "",
    @SerialName("risk_note")
    val riskNote: String = "",
    @SerialName("created_at")
    val createdAt: String = "",
)

@Serializable
data class ExecutionBatch(
    val batch: Int,
    @SerialName("position_pct")
    val positionPct: Double = 0.0,
    val condition: String = "",
    val status: String = "pending",
)

// ==================== 深度复盘模型 ====================

@Serializable
data class DeepReviewResult(
    val mistakes: List<MistakeItem> = emptyList(),
    @SerialName("success_patterns")
    val successPatterns: List<SuccessPattern> = emptyList(),
    @SerialName("improvement_plan")
    val improvementPlan: ImprovementPlan? = null,
)

@Serializable
data class MistakeItem(
    val type: String,
    val name: String,
    val trade: Map<String, String> = emptyMap(),
    val lesson: String = "",
    val severity: String = "medium",
)

@Serializable
data class SuccessPattern(
    val pattern: String,
    val count: Int = 0,
    @SerialName("win_rate")
    val winRate: Double = 0.0,
    @SerialName("avg_return_pct")
    val avgReturnPct: Double = 0.0,
    val suggestion: String = "",
)

@Serializable
data class ImprovementPlan(
    val improvements: List<String> = emptyList(),
    val priorities: List<PriorityItem> = emptyList(),
    @SerialName("overall_assessment")
    val overallAssessment: String = "",
)

@Serializable
data class PriorityItem(
    val priority: Int = 0,
    val action: String = "",
)

// ==================== 周报/月报模型 ====================

@Serializable
data class PeriodicReport(
    val type: String,
    val period: ReportPeriod = ReportPeriod(),
    val summary: ReportSummary = ReportSummary(),
    val attribution: ReportAttribution = ReportAttribution(),
    @SerialName("best_trades")
    val bestTrades: List<ReportTrade> = emptyList(),
    @SerialName("worst_trades")
    val worstTrades: List<ReportTrade> = emptyList(),
    val lessons: List<String> = emptyList(),
    @SerialName("next_week_suggestions")
    val nextWeekSuggestions: List<String> = emptyList(),
    @SerialName("generated_at")
    val generatedAt: String = "",
)

@Serializable
data class ReportPeriod(
    val start: String = "",
    val end: String = "",
)

@Serializable
data class ReportSummary(
    @SerialName("total_trades")
    val totalTrades: Int = 0,
    @SerialName("win_count")
    val winCount: Int = 0,
    @SerialName("loss_count")
    val lossCount: Int = 0,
    @SerialName("win_rate")
    val winRate: Double = 0.0,
    @SerialName("total_pnl_pct")
    val totalPnlPct: Double = 0.0,
    @SerialName("avg_pnl_pct")
    val avgPnlPct: Double = 0.0,
    @SerialName("max_win_pct")
    val maxWinPct: Double = 0.0,
    @SerialName("max_loss_pct")
    val maxLossPct: Double = 0.0,
)

@Serializable
data class ReportAttribution(
    @SerialName("by_strategy")
    val byStrategy: Map<String, Double> = emptyMap(),
    @SerialName("by_sector")
    val bySector: Map<String, Double> = emptyMap(),
)

@Serializable
data class ReportTrade(
    val symbol: String = "",
    val name: String = "",
    @SerialName("pnl_pct")
    val pnlPct: Double = 0.0,
    val strategy: String = "",
)

// ==================== 交易风格模型 ====================

@Serializable
data class TradingStyle(
    @SerialName("avg_hold_days")
    val avgHoldDays: Double = 0.0,
    @SerialName("stop_loss_preference")
    val stopLossPreference: Double = -5.0,
    @SerialName("take_profit_preference")
    val takeProfitPreference: Double = 8.0,
    @SerialName("position_style")
    val positionStyle: String = "moderate",
    @SerialName("win_rate")
    val winRate: Double = 0.0,
    @SerialName("avg_profit_pct")
    val avgProfitPct: Double = 0.0,
    @SerialName("avg_loss_pct")
    val avgLossPct: Double = 0.0,
    @SerialName("profit_loss_ratio")
    val profitLossRatio: Double = 0.0,
    @SerialName("trade_frequency")
    val tradeFrequency: String = "normal",
    @SerialName("favorite_sectors")
    val favoriteSectors: List<String> = emptyList(),
    val weaknesses: List<String> = emptyList(),
    val strengths: List<String> = emptyList(),
    @SerialName("risk_tolerance")
    val riskTolerance: Double = 0.5,
)

// ==================== 知识库模型 ====================

@Serializable
data class KnowledgeTopic(
    val key: String,
    val title: String,
    val category: String,
)

@Serializable
data class KnowledgeArticle(
    val title: String,
    val category: String = "",
    val content: String,
)

// ==================== 数据质量模型 ====================

@Serializable
data class DataQualityReport(
    @SerialName("overall_score")
    val overallScore: Double = 0.0,
    val completeness: Double = 0.0,
    val timeliness: Double = 0.0,
    val accuracy: Double = 0.0,
    val consistency: Double = 0.0,
    val issues: List<DataQualityIssue> = emptyList(),
    @SerialName("issue_count")
    val issueCount: Int = 0,
    @SerialName("critical_issues")
    val criticalIssues: Int = 0,
    @SerialName("checked_at")
    val checkedAt: String = "",
)

@Serializable
data class DataQualityIssue(
    val type: String,
    val severity: String,
    val message: String,
)

// ==================== 上下文问答模型 ====================

@Serializable
data class ContextQAResult(
    val answer: String,
    val source: String = "",
    @SerialName("question_type")
    val questionType: String = "",
    val suggestions: List<String> = emptyList(),
    @SerialName("context_page")
    val contextPage: String = "",
)
