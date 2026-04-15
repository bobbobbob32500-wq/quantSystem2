package com.quant.system.data.api

import com.quant.system.data.model.ActionRequest
import com.quant.system.data.model.ActionResponse
import com.quant.system.data.model.ActionRecord
import com.quant.system.data.model.BackgroundTaskRecord
import com.quant.system.data.model.AnalyticsSummaryPayload
import com.quant.system.data.model.AppUpdatePayload
import com.quant.system.data.model.ApiResponse
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.HealthResponse
import com.quant.system.data.model.RootResponse
import com.quant.system.data.model.StockDetailPayload
import com.quant.system.data.model.StrategyMeta
import com.quant.system.data.model.VirtualTradeUpsertRequest
import com.quant.system.data.model.WatchlistPayload
import com.quant.system.data.model.AIStatus
import com.quant.system.data.model.AIChatRequest
import com.quant.system.data.model.AIChatResponse
import com.quant.system.data.model.AIQuickAskRequest
import com.quant.system.data.model.ButlerStatus
import com.quant.system.data.model.AIBriefingRequest
import com.quant.system.data.model.AIBriefingResult
import com.quant.system.data.model.AIMonitorRequest
import com.quant.system.data.model.AIMonitorResult
import com.quant.system.data.model.AIReviewRequest
import com.quant.system.data.model.AIReviewResult
import com.quant.system.data.model.AIRiskCheckRequest
import com.quant.system.data.model.AIRiskCheckResult
import com.quant.system.data.model.AISignalAnalysisRequest
import com.quant.system.data.model.AISignalAnalysisResult
import com.quant.system.data.model.AIResultResponse
import com.quant.system.data.model.AlertItem
import com.quant.system.data.model.AlertSummary
import com.quant.system.data.model.PriceAlertItem
import com.quant.system.data.model.WatcherSummary
import com.quant.system.data.model.StrategyOptimizationResult
import com.quant.system.data.model.MarketAdaptiveResult
import com.quant.system.data.model.ExecutionPlan
import com.quant.system.data.model.DeepReviewResult
import com.quant.system.data.model.PeriodicReport
import com.quant.system.data.model.TradingStyle
import com.quant.system.data.model.KnowledgeTopic
import com.quant.system.data.model.KnowledgeArticle
import com.quant.system.data.model.DataQualityReport
import com.quant.system.data.model.ContextQAResult
import retrofit2.http.DELETE
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path

interface ApiService {
    @GET("/")
    suspend fun getRoot(): RootResponse

    @GET("/api/health")
    suspend fun getHealth(): HealthResponse

    @GET("/api/dashboard")
    suspend fun getDashboard(): ApiResponse<DashboardSnapshot>

    @GET("/api/dashboard/overview")
    suspend fun getOverview(): ApiResponse<DashboardSnapshot>

    @GET("/api/action_records")
    suspend fun getActionRecords(
        @retrofit2.http.Query("limit") limit: Int = 30,
    ): ApiResponse<List<ActionRecord>>

    @GET("/api/background_tasks")
    suspend fun getBackgroundTasks(
        @retrofit2.http.Query("limit") limit: Int = 30,
    ): ApiResponse<List<BackgroundTaskRecord>>

    @POST("/api/background_tasks/{task_id}/retry")
    suspend fun retryBackgroundTask(@Path("task_id") taskId: String): ApiResponse<ActionResponse>

    @GET("/api/stocks/{symbol}/detail")
    suspend fun getStockDetail(@Path("symbol") symbol: String): ApiResponse<StockDetailPayload>

    @GET("/api/strategies")
    suspend fun getStrategies(): ApiResponse<List<StrategyMeta>>

    @GET("/api/strategies/{strategy_id}")
    suspend fun getStrategyDetail(@Path("strategy_id") strategyId: String): ApiResponse<StrategyMeta>

    @POST("/api/strategies/{strategy_id}/run")
    suspend fun runStrategy(
        @Path("strategy_id") strategyId: String,
        @Body request: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    ): ApiResponse<ActionResponse>

    @GET("/api/analytics/summary")
    suspend fun getAnalyticsSummary(): ApiResponse<AnalyticsSummaryPayload>

    @GET("/api/watchlist")
    suspend fun getWatchlist(): ApiResponse<WatchlistPayload>

    @POST("/api/watchlist")
    suspend fun updateWatchlist(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<WatchlistPayload>

    @GET("/api/app_update/android/latest")
    suspend fun getAndroidLatestUpdate(): ApiResponse<AppUpdatePayload>

    @POST("/api/action")
    suspend fun executeAction(@Body request: ActionRequest): ApiResponse<ActionResponse>

    @POST("/api/virtual_trades")
    suspend fun createVirtualTrade(@Body request: VirtualTradeUpsertRequest): ApiResponse<Map<String, String>>

    @PUT("/api/virtual_trades/{trade_id}")
    suspend fun updateVirtualTrade(
        @Path("trade_id") tradeId: String,
        @Body request: VirtualTradeUpsertRequest,
    ): ApiResponse<Map<String, String>>

    @DELETE("/api/virtual_trades/{trade_id}")
    suspend fun deleteVirtualTrade(@Path("trade_id") tradeId: String): ApiResponse<Map<String, String>>

    // ==================== AI管家接口 ====================

    @GET("/api/ai/status")
    suspend fun getAIStatus(): AIStatus

    @POST("/api/ai/chat")
    suspend fun aiChat(@Body request: AIChatRequest): AIChatResponse

    @POST("/api/ai/quick_ask")
    suspend fun aiQuickAsk(@Body request: AIQuickAskRequest): AIChatResponse

    @GET("/api/butler/status")
    suspend fun getButlerStatus(): ButlerStatus

    @POST("/api/butler/start")
    suspend fun startButler(): ApiResponse<Map<String, String>>

    @POST("/api/butler/stop")
    suspend fun stopButler(): ApiResponse<Map<String, String>>

    @POST("/api/butler/briefing")
    suspend fun generateBriefing(@Body request: AIBriefingRequest): AIResultResponse<AIBriefingResult>

    @POST("/api/butler/monitor")
    suspend fun doMonitor(@Body request: AIMonitorRequest): AIResultResponse<AIMonitorResult>

    @POST("/api/butler/review")
    suspend fun generateReview(@Body request: AIReviewRequest): AIResultResponse<AIReviewResult>

    @POST("/api/butler/risk_check")
    suspend fun doRiskCheck(@Body request: AIRiskCheckRequest): AIResultResponse<AIRiskCheckResult>

    @POST("/api/butler/signal_analysis")
    suspend fun analyzeSignal(@Body request: AISignalAnalysisRequest): AIResultResponse<AISignalAnalysisResult>

    // ==================== 扩展功能接口 ====================

    // --- 多维度预警 ---
    @GET("/api/alerts/active")
    suspend fun getActiveAlerts(): ApiResponse<List<AlertItem>>

    @GET("/api/alerts/summary")
    suspend fun getAlertSummary(): ApiResponse<AlertSummary>

    @POST("/api/alerts/{alert_id}/ack")
    suspend fun ackAlert(@Path("alert_id") alertId: String): ApiResponse<Map<String, String>>

    // --- 实时盯盘 ---
    @GET("/api/watcher/alerts")
    suspend fun getWatcherAlerts(): ApiResponse<List<PriceAlertItem>>

    @DELETE("/api/watcher/alerts/{alert_id}")
    suspend fun removeWatcherAlert(@Path("alert_id") alertId: String): ApiResponse<Map<String, String>>

    @GET("/api/watcher/summary")
    suspend fun getWatcherSummary(): ApiResponse<WatcherSummary>

    // --- 策略优化 ---
    @POST("/api/strategy/optimize")
    suspend fun optimizeStrategy(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<StrategyOptimizationResult>

    @POST("/api/strategy/market_adaptive")
    suspend fun marketAdaptiveParams(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<MarketAdaptiveResult>

    // --- 智能执行 ---
    @POST("/api/execution/plan")
    suspend fun generateExecutionPlan(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<ExecutionPlan>

    @GET("/api/execution/plans")
    suspend fun getExecutionPlans(): ApiResponse<List<ExecutionPlan>>

    // --- 深度复盘 ---
    @POST("/api/review/deep")
    suspend fun deepReview(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<DeepReviewResult>

    // --- 周报/月报 ---
    @POST("/api/reports/generate")
    suspend fun generateReport(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<PeriodicReport>

    // --- 交易风格 ---
    @POST("/api/style/analyze")
    suspend fun analyzeTradingStyle(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<TradingStyle>

    @GET("/api/style")
    suspend fun getTradingStyle(): ApiResponse<TradingStyle>

    // --- 上下文问答 ---
    @POST("/api/ai/context_qa")
    suspend fun contextQA(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<ContextQAResult>

    // --- 知识库 ---
    @GET("/api/knowledge/topics")
    suspend fun listKnowledgeTopics(@retrofit2.http.Query("category") category: String? = null): ApiResponse<List<KnowledgeTopic>>

    @GET("/api/knowledge/query")
    suspend fun queryKnowledge(@retrofit2.http.Query("topic") topic: String): ApiResponse<KnowledgeArticle>

    @GET("/api/knowledge/categories")
    suspend fun getKnowledgeCategories(): ApiResponse<List<String>>

    // --- 数据质量 ---
    @POST("/api/data_quality/check")
    suspend fun checkDataQuality(@Body request: Map<String, @JvmSuppressWildcards Any>): ApiResponse<DataQualityReport>

    @GET("/api/data_quality/summary")
    suspend fun getDataQualitySummary(): ApiResponse<Map<String, String>>
}
