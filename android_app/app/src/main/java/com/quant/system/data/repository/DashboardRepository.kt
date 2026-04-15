package com.quant.system.data.repository

import android.content.Context
import com.quant.system.core.network.EnhancedRetrofitClient
import com.quant.system.core.network.NetworkMonitor
import com.quant.system.core.network.NetworkMonitorImpl
import com.quant.system.core.network.NetworkQuality
import com.quant.system.data.api.ApiService
import com.quant.system.data.model.ActionRecord
import com.quant.system.data.model.ActionRequest
import com.quant.system.data.model.ActionResponse
import com.quant.system.data.model.AnalyticsSummaryPayload
import com.quant.system.data.model.ApiResponse
import com.quant.system.data.model.AppUpdatePayload
import com.quant.system.data.model.BackgroundTaskRecord
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.HealthResponse
import com.quant.system.data.model.RootResponse
import com.quant.system.data.model.StockDetailPayload
import com.quant.system.data.model.StrategyMeta
import com.quant.system.data.model.VirtualTradeUpsertRequest
import com.quant.system.data.model.WatchlistPayload
import com.quant.system.data.model.AlertItem
import com.quant.system.data.model.AlertSummary
import com.quant.system.data.model.PriceAlertItem
import com.quant.system.data.model.WatcherSummary
import com.quant.system.data.model.DeepReviewResult
import com.quant.system.data.model.KnowledgeTopic
import com.quant.system.data.model.KnowledgeArticle
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import retrofit2.HttpException

class DashboardRepository(private val context: Context) {
    private val retrofitClient = EnhancedRetrofitClient(context)
    private val networkMonitor = NetworkMonitorImpl(context)
    
    suspend fun getDashboard(baseUrl: String): Result<DashboardSnapshot> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getOverview()
        response.requireData("数据解析失败")
    }

    suspend fun executeAction(
        baseUrl: String,
        action: String,
        payload: JsonObject? = null,
        confirmed: Boolean = false,
    ): Result<ActionResponse> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.executeAction(
            ActionRequest(
                action = action,
                payload = payload,
                confirmed = confirmed,
            ),
        )
        response.requireData("数据解析失败")
    }

    suspend fun checkHealth(baseUrl: String): Result<HealthResponse> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getHealth()
    }

    suspend fun getRootInfo(baseUrl: String): Result<RootResponse> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getRoot()
    }

    suspend fun getActionRecords(baseUrl: String, limit: Int = 50): Result<List<ActionRecord>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getActionRecords(limit)
        response.requireData("数据解析失败")
    }

    suspend fun getBackgroundTasks(baseUrl: String, limit: Int = 30): Result<List<BackgroundTaskRecord>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getBackgroundTasks(limit)
        response.requireData("数据解析失败")
    }

    suspend fun retryBackgroundTask(baseUrl: String, taskId: String): Result<ActionResponse> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.retryBackgroundTask(taskId)
        response.requireData("重试任务失败")
    }

    suspend fun getStockDetail(baseUrl: String, symbol: String): Result<StockDetailPayload> = safeApiCall(retryOnTransientNetwork = false) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getStockDetail(symbol)
        response.requireData("加载个股详情失败")
    }

    suspend fun getStrategies(baseUrl: String): Result<List<StrategyMeta>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getStrategies()
        response.requireData("加载策略列表失败")
    }

    suspend fun runStrategy(
        baseUrl: String,
        strategyId: String,
        params: Map<String, Any?> = emptyMap(),
    ): Result<ActionResponse> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.runStrategy(
            strategyId = strategyId,
            request = mapOf("params" to params),
        )
        response.requireData("执行策略失败")
    }

    suspend fun getAnalyticsSummary(baseUrl: String): Result<AnalyticsSummaryPayload> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getAnalyticsSummary()
        response.requireData("加载复盘统计失败")
    }

    suspend fun getWatchlist(baseUrl: String): Result<WatchlistPayload> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getWatchlist()
        response.requireData("加载自选池失败")
    }

    suspend fun updateWatchlist(baseUrl: String, symbols: List<String>): Result<WatchlistPayload> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.updateWatchlist(
            request = mapOf("symbols" to symbols),
        )
        response.requireData("保存自选池失败")
    }

    suspend fun getAndroidLatestUpdate(baseUrl: String): Result<AppUpdatePayload> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.getAndroidLatestUpdate()
        response.requireData("数据解析失败")
    }

    suspend fun createVirtualTrade(
        baseUrl: String,
        symbol: String,
        name: String,
        buyPrice: Double,
        quantity: Int,
    ): Result<Unit> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.createVirtualTrade(
            VirtualTradeUpsertRequest(
                symbol = symbol,
                name = name,
                buyPrice = buyPrice,
                quantity = quantity,
            ),
        )
        response.requireData("新增持仓失败")
        Unit
    }

    suspend fun updateVirtualTrade(
        baseUrl: String,
        tradeId: String,
        symbol: String,
        name: String,
        buyPrice: Double,
        quantity: Int,
    ): Result<Unit> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.updateVirtualTrade(
            tradeId = tradeId,
            request = VirtualTradeUpsertRequest(
                symbol = symbol,
                name = name,
                buyPrice = buyPrice,
                quantity = quantity,
            ),
        )
        response.requireData("更新持仓失败")
        Unit
    }

    suspend fun deleteVirtualTrade(baseUrl: String, tradeId: String): Result<Unit> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.deleteVirtualTrade(tradeId)
        response.requireData("删除持仓失败")
        Unit
    }

    // ==================== 扩展功能API ====================

    suspend fun getActiveAlerts(baseUrl: String): Result<List<AlertItem>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getActiveAlerts().requireData("加载预警失败")
    }

    suspend fun getAlertSummary(baseUrl: String): Result<AlertSummary> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getAlertSummary().requireData("加载预警摘要失败")
    }

    suspend fun ackAlert(baseUrl: String, alertId: String): Result<Map<String, String>> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.ackAlert(alertId).requireData("确认预警失败")
    }

    suspend fun getWatcherAlerts(baseUrl: String): Result<List<PriceAlertItem>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getWatcherAlerts().requireData("加载盯盘提醒失败")
    }

    suspend fun removeWatcherAlert(baseUrl: String, alertId: String): Result<Map<String, String>> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.removeWatcherAlert(alertId).requireData("移除提醒失败")
    }

    suspend fun getWatcherSummary(baseUrl: String): Result<WatcherSummary> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getWatcherSummary().requireData("加载盯盘摘要失败")
    }

    suspend fun deepReview(baseUrl: String, trades: List<Map<String, String>>): Result<DeepReviewResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.deepReview(mapOf("trades" to trades)).requireData("深度复盘失败")
    }

    suspend fun listKnowledgeTopics(baseUrl: String): Result<List<KnowledgeTopic>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.listKnowledgeTopics().requireData("加载知识主题失败")
    }

    suspend fun getKnowledgeCategories(baseUrl: String): Result<List<String>> = safeApiCall(retryOnTransientNetwork = true) {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getKnowledgeCategories().requireData("加载知识分类失败")
    }

    suspend fun queryKnowledge(baseUrl: String, topic: String): Result<KnowledgeArticle> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.queryKnowledge(topic).requireData("查询知识失败")
    }

    private suspend fun <T> safeApiCall(
        retryOnTransientNetwork: Boolean = false,
        block: suspend () -> T,
    ): Result<T> {
        // 检查网络状态
        val networkState = try {
            networkMonitor.networkState.first()
        } catch (e: Exception) {
            null
        }
        
        // 根据网络质量调整重试策略
        val maxAttempts = calculateMaxAttempts(retryOnTransientNetwork, networkState)
        var attempt = 1
        var lastFailure: Throwable? = null

        while (attempt <= maxAttempts) {
            try {
                return Result.success(block())
            } catch (raw: Throwable) {
                val wrapped = IllegalStateException(mapErrorMessage(raw), raw)
                lastFailure = wrapped
                
                // 检查是否应该重试
                val canRetry = shouldRetry(
                    attempt = attempt,
                    maxAttempts = maxAttempts,
                    error = raw,
                    retryOnTransientNetwork = retryOnTransientNetwork,
                    networkState = networkState
                )
                
                if (!canRetry) {
                    return Result.failure(wrapped)
                }
                
                // 智能延迟：根据网络质量和重试次数计算延迟
                val delayMs = calculateRetryDelay(attempt, networkState)
                delay(delayMs)
                attempt += 1
            }
        }

        return Result.failure(lastFailure ?: IllegalStateException("请求失败"))
    }
    
    private fun calculateMaxAttempts(retryOnTransientNetwork: Boolean, networkState: NetworkState?): Int {
        if (!retryOnTransientNetwork) return 1
        
        return when (networkState?.let { NetworkMonitor.getNetworkQualityLevel(it.networkQuality) }) {
            NetworkQuality.EXCELLENT -> 3
            NetworkQuality.GOOD -> 3
            NetworkQuality.FAIR -> 2
            NetworkQuality.POOR -> 1
            NetworkQuality.VERY_POOR -> 1
            NetworkQuality.OFFLINE -> 0
            null -> 2
        }
    }
    
    private fun shouldRetry(
        attempt: Int,
        maxAttempts: Int,
        error: Throwable,
        retryOnTransientNetwork: Boolean,
        networkState: NetworkState?
    ): Boolean {
        if (attempt >= maxAttempts) return false
        if (!retryOnTransientNetwork) return false
        
        // 检查错误类型是否可重试
        if (!isTransientRetryable(error)) return false
        
        // 检查网络状态
        return when (networkState?.let { NetworkMonitor.getNetworkQualityLevel(it.networkQuality) }) {
            NetworkQuality.OFFLINE -> false
            NetworkQuality.VERY_POOR -> attempt == 1 // 极差网络只重试一次
            else -> true
        }
    }
    
    private fun calculateRetryDelay(attempt: Int, networkState: NetworkState?): Long {
        // 基础延迟
        var delayMs = when (attempt) {
            1 -> 1000L
            2 -> 3000L
            else -> 5000L
        }
        
        // 根据网络质量调整延迟
        networkState?.let { state ->
            val qualityLevel = NetworkMonitor.getNetworkQualityLevel(state.networkQuality)
            when (qualityLevel) {
                NetworkQuality.EXCELLENT -> delayMs *= 1
                NetworkQuality.GOOD -> delayMs *= 1
                NetworkQuality.FAIR -> delayMs *= 2
                NetworkQuality.POOR -> delayMs *= 3
                NetworkQuality.VERY_POOR -> delayMs *= 5
                NetworkQuality.OFFLINE -> delayMs = 0L
            }
        }
        
        return delayMs.coerceAtMost(30000L) // 最大30秒
    }

    private fun <T> ApiResponse<T>.requireData(fallbackDetail: String): T {
        if (!success || data == null) {
            throw IllegalStateException(detail?.takeIf { it.isNotBlank() } ?: fallbackDetail)
        }
        return data
    }

    private fun mapErrorMessage(error: Throwable): String {
        return when (error) {
            is SocketTimeoutException,
            is InterruptedIOException -> "请求超时，请稍后重试"
            is UnknownHostException,
            is ConnectException,
            is IOException -> "网络不可用或服务器不可达"
            is HttpException -> "服务器错误（${error.code()}）"
            is SerializationException -> "数据解析失败"
            is IllegalStateException -> error.message ?: "数据解析失败"
            else -> "请求失败：${error.message ?: "未知错误"}"
        }
    }

    private fun isTransientRetryable(error: Throwable): Boolean {
        return when (error) {
            is SocketTimeoutException,
            is InterruptedIOException -> false
            is UnknownHostException,
            is ConnectException,
            is IOException -> true
            is HttpException -> error.code() in setOf(429, 502, 503, 504)
            else -> false
        }
    }

    private companion object {
        const val RETRY_BASE_DELAY_MS = 400L
    }
}
