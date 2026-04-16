package com.quant.system.core.network

import android.content.Context
import com.quant.system.BuildConfig
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import okhttp3.Cache
import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.math.pow

/**
 * 增强的Retrofit客户端，提供智能网络管理和优化
 */
class EnhancedRetrofitClient(private val context: Context) {
    private val networkMonitor = NetworkMonitorImpl(context)
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    
    private val _networkState = MutableStateFlow(NetworkState(isConnected = false, networkType = NetworkType.UNKNOWN, networkQuality = 0))
    val networkState: StateFlow<NetworkState> = _networkState.asStateFlow()
    
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }
    
    private val cacheDir = File(context.cacheDir, "http_cache")
    private val cacheSize = 10L * 1024 * 1024 // 10MB
    
    private val connectionPool = ConnectionPool(
        maxIdleConnections = 5,
        keepAliveDuration = 5,
        timeUnit = TimeUnit.MINUTES
    )
    
    private val dispatcher = Dispatcher().apply {
        maxRequests = 20
        maxRequestsPerHost = 5
    }
    
    /** 常规接口超时 */
    private val okHttpClient = buildOkHttpClient(
        readTimeoutSec = 30,
        writeTimeoutSec = 30,
        callTimeoutSec = 60,
    )

    /**
     * 大模型对话、管家类接口：云端推理耗时常超过 60 秒，单独使用更长读超时，避免误报失败。
     */
    private val longReadOkHttpClient = buildOkHttpClient(
        readTimeoutSec = 120,
        writeTimeoutSec = 60,
        callTimeoutSec = 180,
    )

    private fun buildOkHttpClient(
        readTimeoutSec: Long,
        writeTimeoutSec: Long,
        callTimeoutSec: Long,
    ): OkHttpClient = OkHttpClient.Builder().apply {
        connectionPool(connectionPool)
        dispatcher(dispatcher)
        cache(Cache(cacheDir, cacheSize))
        connectTimeout(15, TimeUnit.SECONDS)
        readTimeout(readTimeoutSec, TimeUnit.SECONDS)
        writeTimeout(writeTimeoutSec, TimeUnit.SECONDS)
        callTimeout(callTimeoutSec, TimeUnit.SECONDS)
        retryOnConnectionFailure(true)
        addInterceptor(NetworkAwareInterceptor())
        addInterceptor(RetryInterceptor())
        addInterceptor(CacheControlInterceptor())
        if (BuildConfig.DEBUG) {
            val logging = HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BASIC
            }
            addInterceptor(logging)
        }
    }.build()
    
    private val serviceCache = ConcurrentHashMap<String, Any>()
    
    init {
        // 监听网络状态变化
        scope.launch {
            networkMonitor.networkState.collectLatest { state ->
                _networkState.value = state
                updateClientConfiguration(state)
            }
        }
    }
    
    /**
     * 根据网络状态更新客户端配置
     */
    private fun updateClientConfiguration(state: NetworkState) {
        // 这里可以动态调整超时时间、重试策略等
        // 例如：弱网环境下增加超时时间，减少重试次数
    }
    
    /**
     * 创建API服务
     * @param longReadTimeout 为 true 时使用更长读超时，适用于大模型对话、管家推理等接口
     */
    fun <T> createApiService(
        baseUrl: String,
        serviceClass: Class<T>,
        longReadTimeout: Boolean = false,
    ): T {
        val normalizedBaseUrl = normalizeBaseUrl(baseUrl)
        val cacheKey = "$normalizedBaseUrl-${serviceClass.name}-lr:$longReadTimeout"
        @Suppress("UNCHECKED_CAST")
        return serviceCache.getOrPut(cacheKey) {
            Retrofit.Builder()
                .baseUrl(normalizedBaseUrl)
                .client(if (longReadTimeout) longReadOkHttpClient else okHttpClient)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(serviceClass)
        } as T
    }
    
    /**
     * 网络感知拦截器
     */
    private inner class NetworkAwareInterceptor : Interceptor {
        override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
            val request = chain.request()
            
            // 检查网络状态
            if (!networkMonitor.isNetworkAvailable()) {
                // 如果网络不可用，尝试使用缓存
                val cachedRequest = request.newBuilder()
                    .header("Cache-Control", "public, only-if-cached, max-stale=${60 * 60 * 24 * 7}") // 7天
                    .build()
                
                return try {
                    chain.proceed(cachedRequest)
                } catch (e: Exception) {
                    throw NetworkUnavailableException("网络不可用，且无缓存数据", e)
                }
            }
            
            // 根据网络质量调整请求
            val networkState = networkState.value
            val modifiedRequest = when (NetworkMonitor.getNetworkQualityLevel(networkState.networkQuality)) {
                NetworkQuality.VERY_POOR, NetworkQuality.POOR -> {
                    // 弱网环境下，优先使用缓存，减少数据量
                    request.newBuilder()
                        .header("Cache-Control", "public, max-age=60") // 缓存60秒
                        .header("Accept-Encoding", "gzip") // 启用压缩
                        .build()
                }
                else -> {
                    // 良好网络环境下，使用正常策略
                    request
                }
            }
            
            return chain.proceed(modifiedRequest)
        }
    }
    
    /**
     * 智能重试拦截器
     */
    private inner class RetryInterceptor : Interceptor {
        override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
            val request = chain.request()
            var response: okhttp3.Response? = null
            var lastException: Exception? = null
            
            val maxRetries = calculateMaxRetries()
            val retryDelayBase = calculateRetryDelayBase()
            
            for (attempt in 1..maxRetries) {
                try {
                    response = chain.proceed(request)
                    
                    // 检查响应状态码
                    when (response.code) {
                        in 200..299 -> {
                            // 成功响应
                            return response
                        }
                        in 500..599 -> {
                            // 服务器错误，需要重试
                            response.close()
                            if (attempt < maxRetries) {
                                delay(retryDelayBase * attempt.toDouble().pow(1.5).toLong())
                                continue
                            }
                        }
                        429 -> {
                            // 请求过多，需要退避
                            response.close()
                            val retryAfter = response.header("Retry-After")?.toLongOrNull() ?: 60L
                            delay(retryAfter * 1000)
                            if (attempt < maxRetries) continue
                        }
                        else -> {
                            // 其他错误，不重试
                            return response
                        }
                    }
                } catch (e: Exception) {
                    lastException = e
                    
                    // 检查是否为可重试的异常
                    if (isRetryableException(e) && attempt < maxRetries) {
                        // 指数退避延迟
                        val delayMs = retryDelayBase * (2.0.pow(attempt - 1).toLong())
                        delay(delayMs)
                        continue
                    } else {
                        break
                    }
                }
            }
            
            // 所有重试都失败
            response?.close()
            throw lastException ?: RuntimeException("请求失败")
        }
        
        private fun calculateMaxRetries(): Int {
            return when (NetworkMonitor.getNetworkQualityLevel(networkState.value.networkQuality)) {
                NetworkQuality.EXCELLENT -> 2
                NetworkQuality.GOOD -> 3
                NetworkQuality.FAIR -> 2
                NetworkQuality.POOR -> 1
                NetworkQuality.VERY_POOR -> 0
                NetworkQuality.OFFLINE -> 0
            }
        }
        
        private fun calculateRetryDelayBase(): Long {
            return NetworkMonitor.getSuggestedRetryDelay(
                networkState.value.networkType,
                networkState.value.networkQuality
            )
        }
        
        private fun isRetryableException(e: Exception): Boolean {
            return when (e) {
                is java.net.SocketTimeoutException,
                is java.net.ConnectException,
                is java.net.UnknownHostException,
                is java.io.IOException -> true
                else -> false
            }
        }
        
        private fun delay(millis: Long) {
            try {
                Thread.sleep(millis)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
    }
    
    /**
     * 缓存控制拦截器
     */
    private inner class CacheControlInterceptor : Interceptor {
        override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
            val request = chain.request()
            val originalResponse = chain.proceed(request)
            
            // 根据响应类型设置缓存策略
            return when {
                request.method == "GET" -> {
                    val cacheControl = when {
                        // 静态资源缓存1小时
                        request.url.toString().contains("/static/") -> "public, max-age=${60 * 60}"
                        // API数据缓存5分钟
                        request.url.toString().contains("/api/") -> "public, max-age=${5 * 60}"
                        // 默认缓存1分钟
                        else -> "public, max-age=60"
                    }
                    
                    originalResponse.newBuilder()
                        .header("Cache-Control", cacheControl)
                        .build()
                }
                else -> originalResponse
            }
        }
    }
    
    /**
     * 规范化Base URL
     */
    fun normalizeBaseUrl(baseUrl: String): String {
        val trimmed = baseUrl.trim()
        if (trimmed.isEmpty()) {
            return BuildConfig.API_BASE_URL
        }
        return if (trimmed.endsWith("/")) trimmed else "$trimmed/"
    }
    
    /**
     * 清理缓存
     */
    fun clearCache() {
        try {
            okHttpClient.cache?.evictAll()
        } catch (e: Exception) {
            // 忽略清理错误
        }
    }
    
    /**
     * 获取缓存统计信息
     */
    fun getCacheStats(): CacheStats {
        val cache = okHttpClient.cache ?: return CacheStats()
        
        return try {
            CacheStats(
                hitCount = cache.hitCount(),
                networkCount = cache.networkCount(),
                requestCount = cache.requestCount(),
                size = cache.size(),
                maxSize = cache.maxSize()
            )
        } catch (e: Exception) {
            CacheStats()
        }
    }
    
    /**
     * 网络不可用异常
     */
    class NetworkUnavailableException(message: String, cause: Throwable? = null) : Exception(message, cause)
    
    /**
     * 缓存统计信息
     */
    data class CacheStats(
        val hitCount: Int = 0,
        val networkCount: Int = 0,
        val requestCount: Int = 0,
        val size: Long = 0,
        val maxSize: Long = 0
    ) {
        val hitRate: Double
            get() = if (requestCount > 0) hitCount.toDouble() / requestCount else 0.0
        
        val usagePercentage: Double
            get() = if (maxSize > 0) size.toDouble() / maxSize else 0.0
    }
}