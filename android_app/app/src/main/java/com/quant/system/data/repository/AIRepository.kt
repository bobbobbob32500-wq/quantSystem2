package com.quant.system.data.repository

import android.content.Context
import com.quant.system.core.network.EnhancedRetrofitClient
import com.quant.system.data.api.ApiService
import com.quant.system.data.model.*
import java.io.IOException
import kotlinx.coroutines.delay
import retrofit2.HttpException

class AIRepository(private val context: Context) {
    private val retrofitClient = EnhancedRetrofitClient(context)
    
    /**
     * 获取AI服务状态
     */
    suspend fun getAIStatus(baseUrl: String): Result<AIStatus> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getAIStatus()
    }
    
    /**
     * AI对话
     */
    suspend fun aiChat(baseUrl: String, message: String, context: Map<String, String>? = null): Result<String> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.aiChat(AIChatRequest(message, context))
        if (response.success) {
            response.response ?: throw IllegalStateException("AI响应为空")
        } else {
            throw IllegalStateException(response.message ?: "AI对话失败")
        }
    }
    
    /**
     * 快速预设问答
     */
    suspend fun aiQuickAsk(baseUrl: String, key: String): Result<String> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.aiQuickAsk(AIQuickAskRequest(key))
        if (response.success) {
            response.response ?: throw IllegalStateException("AI响应为空")
        } else {
            throw IllegalStateException(response.message ?: "快速问答失败")
        }
    }
    
    /**
     * 获取管家状态
     */
    suspend fun getButlerStatus(baseUrl: String): Result<ButlerStatus> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        apiService.getButlerStatus()
    }
    
    /**
     * 启动管家服务
     */
    suspend fun startButler(baseUrl: String): Result<String> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.startButler()
        if (response.success) {
            response.data?.get("message") ?: "AI管家服务已启动"
        } else {
            throw IllegalStateException("启动管家失败")
        }
    }
    
    /**
     * 停止管家服务
     */
    suspend fun stopButler(baseUrl: String): Result<String> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val response = apiService.stopButler()
        if (response.success) {
            response.data?.get("message") ?: "AI管家服务已停止"
        } else {
            throw IllegalStateException("停止管家失败")
        }
    }
    
    /**
     * 生成盘前简报
     */
    suspend fun generateBriefing(
        baseUrl: String,
        yesterdayReview: Map<String, String>? = null,
        todaySelection: List<Map<String, String>>? = null,
        overnightNews: List<Map<String, String>>? = null,
        dataStatus: Map<String, String>? = null,
    ): Result<AIBriefingResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val request = AIBriefingRequest(
            yesterdayReview = yesterdayReview,
            todaySelection = todaySelection,
            overnightNews = overnightNews,
            dataStatus = dataStatus,
        )
        val response = apiService.generateBriefing(request)
        if (response.success && response.result != null) {
            response.result
        } else {
            throw IllegalStateException(response.message ?: "生成盘前简报失败")
        }
    }
    
    /**
     * 执行盘中监控
     */
    suspend fun doMonitor(
        baseUrl: String,
        holdings: List<Map<String, String>>? = null,
        signals: List<Map<String, String>>? = null,
        marketStatus: Map<String, String>? = null,
    ): Result<AIMonitorResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val request = AIMonitorRequest(
            holdings = holdings,
            signals = signals,
            marketStatus = marketStatus,
        )
        val response = apiService.doMonitor(request)
        if (response.success && response.result != null) {
            response.result
        } else {
            throw IllegalStateException(response.message ?: "盘中监控失败")
        }
    }
    
    /**
     * 生成盘后复盘
     */
    suspend fun generateReview(
        baseUrl: String,
        todayTrades: List<Map<String, String>>? = null,
        todaySignals: List<Map<String, String>>? = null,
        holdings: List<Map<String, String>>? = null,
        marketSummary: Map<String, String>? = null,
    ): Result<AIReviewResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val request = AIReviewRequest(
            todayTrades = todayTrades,
            todaySignals = todaySignals,
            holdings = holdings,
            marketSummary = marketSummary,
        )
        val response = apiService.generateReview(request)
        if (response.success && response.result != null) {
            response.result
        } else {
            throw IllegalStateException(response.message ?: "生成盘后复盘失败")
        }
    }
    
    /**
     * 执行风险检查
     */
    suspend fun doRiskCheck(
        baseUrl: String,
        holdings: List<Map<String, String>> = emptyList(),
        marketData: Map<String, String> = emptyMap(),
    ): Result<AIRiskCheckResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val request = AIRiskCheckRequest(
            holdings = holdings,
            marketData = marketData,
        )
        val response = apiService.doRiskCheck(request)
        if (response.success && response.result != null) {
            response.result
        } else {
            throw IllegalStateException(response.message ?: "风险检查失败")
        }
    }
    
    /**
     * 信号实时分析
     */
    suspend fun analyzeSignal(
        baseUrl: String,
        signal: Map<String, String>,
        stockInfo: Map<String, String>,
        position: Map<String, String>? = null,
    ): Result<AISignalAnalysisResult> = safeApiCall {
        val apiService = retrofitClient.createApiService(baseUrl, ApiService::class.java)
        val request = AISignalAnalysisResult(
            signal = signal,
            stockInfo = stockInfo,
            position = position,
        )
        val response = apiService.analyzeSignal(AISignalAnalysisRequest(signal, stockInfo, position))
        if (response.success && response.result != null) {
            response.result
        } else {
            throw IllegalStateException(response.message ?: "信号分析失败")
        }
    }
    
    /**
     * 安全API调用包装器
     */
    private suspend fun <T> safeApiCall(
        retryOnTransientNetwork: Boolean = false,
        maxRetries: Int = 3,
        apiCall: suspend () -> T,
    ): Result<T> {
        var lastException: Exception? = null
        
        for (attempt in 0 until maxRetries) {
            try {
                val result = apiCall()
                return Result.success(result)
            } catch (e: HttpException) {
                return Result.failure(Exception("HTTP ${e.code()}: ${e.message()}"))
            } catch (e: IOException) {
                lastException = e
                if (retryOnTransientNetwork && attempt < maxRetries - 1) {
                    delay(1000L * (attempt + 1))
                    continue
                }
            } catch (e: Exception) {
                return Result.failure(e)
            }
        }
        
        return Result.failure(lastException ?: Exception("未知错误"))
    }
}
