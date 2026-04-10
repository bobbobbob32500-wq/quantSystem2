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
}
