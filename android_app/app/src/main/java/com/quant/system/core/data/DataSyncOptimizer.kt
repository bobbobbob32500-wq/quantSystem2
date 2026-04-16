package com.quant.system.core.data

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.quant.system.core.network.NetworkMonitor
import com.quant.system.core.network.NetworkMonitorImpl
import com.quant.system.core.network.NetworkQuality
import com.quant.system.core.network.NetworkState
import com.quant.system.data.model.DashboardSnapshot
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.util.concurrent.TimeUnit

/**
 * 数据同步优化器
 * 提供智能数据同步、增量更新和缓存管理
 */
class DataSyncOptimizer(private val context: Context) {
    private val networkMonitor = NetworkMonitorImpl(context)
    private val workManager = WorkManager.getInstance(context)
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    
    private val _syncState = MutableStateFlow(SyncState.IDLE)
    val syncState: StateFlow<SyncState> = _syncState.asStateFlow()
    
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }
    
    private var syncJob: Job? = null
    
    init {
        // 监听网络状态变化
        scope.launch {
            networkMonitor.networkState.collectLatest { state ->
                onNetworkStateChanged(state)
            }
        }
    }
    
    /**
     * 启动数据同步
     */
    fun startSync(
        baseUrl: String,
        onSuccess: (DashboardSnapshot) -> Unit,
        onError: (Throwable) -> Unit,
        forceRefresh: Boolean = false
    ) {
        syncJob?.cancel()
        
        syncJob = scope.launch {
            try {
                _syncState.value = SyncState.SYNCING
                
                // 检查网络状态
                val networkState = networkMonitor.networkState.first()
                if (!networkState.isConnected) {
                    // 无网络连接，尝试使用缓存
                    val cachedData = loadCachedData()
                    if (cachedData != null) {
                        onSuccess(cachedData)
                        _syncState.value = SyncState.COMPLETED_CACHED
                        return@launch
                    } else {
                        throw IllegalStateException("网络不可用且无缓存数据")
                    }
                }
                
                // 根据网络质量调整同步策略
                val syncStrategy = getSyncStrategy(networkState, forceRefresh)
                
                when (syncStrategy) {
                    SyncStrategy.FULL_REFRESH -> {
                        // 全量刷新
                        val data = fetchFullData(baseUrl)
                        saveToCache(data)
                        onSuccess(data)
                        _syncState.value = SyncState.COMPLETED_FULL
                    }
                    
                    SyncStrategy.INCREMENTAL -> {
                        // 增量更新
                        val cachedData = loadCachedData()
                        if (cachedData != null && !isCacheExpired(cachedData)) {
                            // 先返回缓存数据，然后在后台更新
                            onSuccess(cachedData)
                            _syncState.value = SyncState.COMPLETED_CACHED
                            
                            // 后台增量更新
                            launch {
                                try {
                                    val incrementalData = fetchIncrementalData(baseUrl, cachedData)
                                    val mergedData = mergeData(cachedData, incrementalData)
                                    saveToCache(mergedData)
                                    _syncState.value = SyncState.COMPLETED_INCREMENTAL
                                } catch (e: Exception) {
                                    // 增量更新失败，不影响用户体验
                                }
                            }
                        } else {
                            // 缓存过期或无缓存，全量刷新
                            val data = fetchFullData(baseUrl)
                            saveToCache(data)
                            onSuccess(data)
                            _syncState.value = SyncState.COMPLETED_FULL
                        }
                    }
                    
                    SyncStrategy.CACHE_ONLY -> {
                        // 仅使用缓存（弱网环境）
                        val cachedData = loadCachedData()
                        if (cachedData != null) {
                            onSuccess(cachedData)
                            _syncState.value = SyncState.COMPLETED_CACHED
                        } else {
                            throw IllegalStateException("网络质量差且无缓存数据")
                        }
                    }
                }
                
            } catch (e: Exception) {
                _syncState.value = SyncState.FAILED
                onError(e)
            }
        }
    }
    
    /**
     * 停止数据同步
     */
    fun stopSync() {
        syncJob?.cancel()
        syncJob = null
        _syncState.value = SyncState.IDLE
    }
    
    /**
     * 设置定期同步
     */
    fun schedulePeriodicSync(intervalMinutes: Long = 15) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .setRequiresBatteryNotLow(true)
            .build()
        
        val syncRequest = PeriodicWorkRequestBuilder<DataSyncWorker>(
            intervalMinutes, TimeUnit.MINUTES
        )
            .setConstraints(constraints)
            .setInitialDelay(intervalMinutes, TimeUnit.MINUTES)
            .build()
        
        workManager.enqueueUniquePeriodicWork(
            "data_sync_work",
            ExistingPeriodicWorkPolicy.UPDATE,
            syncRequest
        )
    }
    
    /**
     * 取消定期同步
     */
    fun cancelPeriodicSync() {
        workManager.cancelUniqueWork("data_sync_work")
    }
    
    /**
     * 清理过期缓存
     */
    fun cleanupExpiredCache() {
        scope.launch {
            try {
                val prefs = context.getSharedPreferences("data_sync_cache", Context.MODE_PRIVATE)
                val editor = prefs.edit()
                
                val now = System.currentTimeMillis()
                val cacheKeys = prefs.all.keys.filter { it.startsWith("cache_") }
                
                cacheKeys.forEach { key ->
                    val timestamp = prefs.getLong("${key}_timestamp", 0)
                    if (timestamp > 0 && now - timestamp > CACHE_EXPIRY_MS) {
                        editor.remove(key)
                        editor.remove("${key}_timestamp")
                    }
                }
                
                editor.apply()
            } catch (e: Exception) {
                // 忽略清理错误
            }
        }
    }
    
    /**
     * 获取缓存统计信息
     */
    fun getCacheStats(): CacheStats {
        val prefs = context.getSharedPreferences("data_sync_cache", Context.MODE_PRIVATE)
        val cacheKeys = prefs.all.keys.filter { it.startsWith("cache_") }
        
        var totalSize = 0L
        var expiredCount = 0
        val now = System.currentTimeMillis()
        
        cacheKeys.forEach { key ->
            val data = prefs.getString(key, null)
            totalSize += data?.length?.toLong() ?: 0
            
            val timestamp = prefs.getLong("${key}_timestamp", 0)
            if (timestamp > 0 && now - timestamp > CACHE_EXPIRY_MS) {
                expiredCount++
            }
        }
        
        return CacheStats(
            totalEntries = cacheKeys.size,
            expiredEntries = expiredCount,
            totalSizeBytes = totalSize,
            cacheHits = prefs.getLong("cache_hits", 0),
            cacheMisses = prefs.getLong("cache_misses", 0)
        )
    }
    
    private suspend fun fetchFullData(baseUrl: String): DashboardSnapshot {
        // 这里应该调用实际的API
        // 暂时返回空对象，实际项目中需要实现
        delay(1000) // 模拟网络延迟
        return DashboardSnapshot()
    }
    
    private suspend fun fetchIncrementalData(baseUrl: String, cachedData: DashboardSnapshot): DashboardSnapshot {
        // 这里应该调用增量更新API
        // 暂时返回空对象，实际项目中需要实现
        delay(500) // 模拟网络延迟
        return DashboardSnapshot()
    }
    
    private fun mergeData(cached: DashboardSnapshot, incremental: DashboardSnapshot): DashboardSnapshot {
        // 合并缓存数据和增量数据
        // 这里需要根据实际数据结构实现合并逻辑
        return incremental // 暂时返回增量数据
    }
    
    private fun loadCachedData(): DashboardSnapshot? {
        return try {
            val prefs = context.getSharedPreferences("data_sync_cache", Context.MODE_PRIVATE)
            val cachedJson = prefs.getString("cache_dashboard", null)
            
            if (cachedJson != null) {
                // 更新缓存命中统计
                prefs.edit().putLong("cache_hits", prefs.getLong("cache_hits", 0) + 1).apply()
                json.decodeFromString(DashboardSnapshot.serializer(), cachedJson)
            } else {
                // 更新缓存未命中统计
                prefs.edit().putLong("cache_misses", prefs.getLong("cache_misses", 0) + 1).apply()
                null
            }
        } catch (e: Exception) {
            null
        }
    }
    
    private fun saveToCache(data: DashboardSnapshot) {
        try {
            val prefs = context.getSharedPreferences("data_sync_cache", Context.MODE_PRIVATE)
            val jsonString = json.encodeToString(DashboardSnapshot.serializer(), data)
            
            prefs.edit()
                .putString("cache_dashboard", jsonString)
                .putLong("cache_dashboard_timestamp", System.currentTimeMillis())
                .apply()
        } catch (e: Exception) {
            // 忽略缓存保存错误
        }
    }
    
    private fun isCacheExpired(data: DashboardSnapshot?): Boolean {
        if (data == null) return true
        
        val prefs = context.getSharedPreferences("data_sync_cache", Context.MODE_PRIVATE)
        val timestamp = prefs.getLong("cache_dashboard_timestamp", 0)
        
        if (timestamp == 0L) return true
        
        val now = System.currentTimeMillis()
        val ageMs = now - timestamp
        
        // 根据网络质量调整缓存过期时间
        val networkState = networkMonitor.networkState.value
        val maxAgeMs = when (NetworkMonitor.getNetworkQualityLevel(networkState.networkQuality)) {
            NetworkQuality.EXCELLENT -> CACHE_EXPIRY_FAST_MS
            NetworkQuality.GOOD -> CACHE_EXPIRY_NORMAL_MS
            NetworkQuality.FAIR -> CACHE_EXPIRY_SLOW_MS
            NetworkQuality.POOR -> CACHE_EXPIRY_SLOW_MS
            NetworkQuality.VERY_POOR -> CACHE_EXPIRY_SLOW_MS
            NetworkQuality.OFFLINE -> Long.MAX_VALUE // 离线时永不过期
        }
        
        return ageMs > maxAgeMs
    }
    
    private fun getSyncStrategy(networkState: NetworkState, forceRefresh: Boolean): SyncStrategy {
        if (forceRefresh) return SyncStrategy.FULL_REFRESH
        
        return when (NetworkMonitor.getNetworkQualityLevel(networkState.networkQuality)) {
            NetworkQuality.EXCELLENT, NetworkQuality.GOOD -> SyncStrategy.INCREMENTAL
            NetworkQuality.FAIR -> SyncStrategy.FULL_REFRESH
            NetworkQuality.POOR, NetworkQuality.VERY_POOR -> SyncStrategy.CACHE_ONLY
            NetworkQuality.OFFLINE -> SyncStrategy.CACHE_ONLY
        }
    }
    
    private fun onNetworkStateChanged(state: NetworkState) {
        // 网络状态变化时，可以调整同步策略
        when (NetworkMonitor.getNetworkQualityLevel(state.networkQuality)) {
            NetworkQuality.EXCELLENT, NetworkQuality.GOOD -> {
                // 网络良好，可以恢复定期同步
                schedulePeriodicSync()
            }
            NetworkQuality.FAIR, NetworkQuality.POOR -> {
                // 网络一般，延长同步间隔
                schedulePeriodicSync(intervalMinutes = 30)
            }
            NetworkQuality.VERY_POOR, NetworkQuality.OFFLINE -> {
                // 网络差或离线，暂停同步
                cancelPeriodicSync()
            }
        }
    }
    
    /**
     * 同步状态
     */
    enum class SyncState {
        IDLE,           // 空闲
        SYNCING,        // 同步中
        COMPLETED_FULL, // 全量同步完成
        COMPLETED_INCREMENTAL, // 增量同步完成
        COMPLETED_CACHED, // 使用缓存完成
        FAILED          // 同步失败
    }
    
    /**
     * 同步策略
     */
    enum class SyncStrategy {
        FULL_REFRESH,   // 全量刷新
        INCREMENTAL,    // 增量更新
        CACHE_ONLY      // 仅使用缓存
    }
    
    /**
     * 缓存统计信息
     */
    data class CacheStats(
        val totalEntries: Int = 0,
        val expiredEntries: Int = 0,
        val totalSizeBytes: Long = 0,
        val cacheHits: Long = 0,
        val cacheMisses: Long = 0
    ) {
        val hitRate: Double
            get() = if (cacheHits + cacheMisses > 0) {
                cacheHits.toDouble() / (cacheHits + cacheMisses)
            } else {
                0.0
            }
        
        val expirationRate: Double
            get() = if (totalEntries > 0) {
                expiredEntries.toDouble() / totalEntries
            } else {
                0.0
            }
    }
    
    companion object {
        private const val CACHE_EXPIRY_FAST_MS = 5 * 60 * 1000L    // 5分钟（良好网络）
        private const val CACHE_EXPIRY_NORMAL_MS = 15 * 60 * 1000L  // 15分钟（一般网络）
        private const val CACHE_EXPIRY_SLOW_MS = 30 * 60 * 1000L    // 30分钟（差网络）
        private const val CACHE_EXPIRY_MS = 24 * 60 * 60 * 1000L    // 24小时（强制清理）
    }
}