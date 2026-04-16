package com.quant.system.core.performance

import android.os.Build
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import androidx.annotation.RequiresApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.roundToInt

/**
 * 性能监控器
 * 监控应用性能指标，识别性能瓶颈
 */
class PerformanceMonitor {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val performanceMetrics = ConcurrentHashMap<String, PerformanceMetric>()
    
    private val _performanceState = MutableStateFlow(PerformanceState())
    val performanceState: StateFlow<PerformanceState> = _performanceState.asStateFlow()
    
    private var monitoringJob: Job? = null
    
    /**
     * 开始性能监控
     */
    fun startMonitoring(intervalMs: Long = 5000L) {
        monitoringJob?.cancel()
        monitoringJob = scope.launch {
            while (true) {
                updatePerformanceMetrics()
                delay(intervalMs)
            }
        }
    }
    
    /**
     * 停止性能监控
     */
    fun stopMonitoring() {
        monitoringJob?.cancel()
        monitoringJob = null
    }
    
    /**
     * 记录操作耗时
     */
    fun recordOperation(operationName: String, durationMs: Long) {
        val metric = performanceMetrics.getOrPut(operationName) {
            PerformanceMetric(operationName)
        }
        metric.record(durationMs)
        
        // 如果操作耗时超过阈值，记录警告
        if (durationMs > metric.warningThresholdMs) {
            android.util.Log.w("PerformanceMonitor", "操作 '${operationName}' 耗时 ${durationMs}ms，超过阈值 ${metric.warningThresholdMs}ms")
        }
    }
    
    /**
     * 开始记录操作
     */
    fun startOperation(operationName: String): OperationTracker {
        return OperationTracker(operationName, this)
    }
    
    /**
     * 获取性能报告
     */
    fun getPerformanceReport(): PerformanceReport {
        val metrics = performanceMetrics.values.toList()
        val currentState = _performanceState.value
        
        return PerformanceReport(
            timestamp = System.currentTimeMillis(),
            metrics = metrics,
            memoryUsage = currentState.memoryUsage,
            cpuUsage = currentState.cpuUsage,
            frameRate = currentState.frameRate,
            networkQuality = currentState.networkQuality,
            recommendations = generateRecommendations(metrics, currentState)
        )
    }
    
    /**
     * 清理旧的性能数据
     */
    fun cleanupOldData(maxAgeMs: Long = 24 * 60 * 60 * 1000L) { // 24小时
        val now = System.currentTimeMillis()
        performanceMetrics.values.forEach { metric ->
            metric.cleanupOldData(now - maxAgeMs)
        }
    }
    
    private fun updatePerformanceMetrics() {
        val memoryInfo = getMemoryInfo()
        val cpuInfo = getCpuInfo()
        val frameRate = estimateFrameRate()
        
        _performanceState.value = PerformanceState(
            memoryUsage = memoryInfo,
            cpuUsage = cpuInfo,
            frameRate = frameRate,
            networkQuality = 0, // 需要从网络监控器获取
            timestamp = System.currentTimeMillis()
        )
    }
    
    private fun getMemoryInfo(): MemoryInfo {
        val runtime = Runtime.getRuntime()
        val totalMemory = runtime.totalMemory()
        val freeMemory = runtime.freeMemory()
        val usedMemory = totalMemory - freeMemory
        val maxMemory = runtime.maxMemory()
        
        return MemoryInfo(
            usedBytes = usedMemory,
            totalBytes = totalMemory,
            maxBytes = maxMemory,
            usagePercentage = (usedMemory.toDouble() / totalMemory.toDouble() * 100).roundToInt()
        )
    }
    
    @RequiresApi(Build.VERSION_CODES.O)
    private fun getCpuInfo(): CpuInfo {
        return try {
            val pid = Process.myPid()
            val statFile = "/proc/$pid/stat"
            val lines = java.io.File(statFile).readLines()
            
            if (lines.isNotEmpty()) {
                val parts = lines[0].split(" ")
                if (parts.size >= 15) {
                    val utime = parts[13].toLongOrNull() ?: 0L
                    val stime = parts[14].toLongOrNull() ?: 0L
                    
                    return CpuInfo(
                        processCpuTimeMs = (utime + stime) / 1000, // 转换为毫秒
                        cpuUsagePercentage = 0 // 需要计算变化率
                    )
                }
            }
            CpuInfo()
        } catch (e: Exception) {
            CpuInfo()
        }
    }
    
    private fun estimateFrameRate(): Int {
        // 简化实现，实际项目中应该使用Choreographer或FrameMetrics
        return 60 // 默认60fps
    }
    
    private fun generateRecommendations(
        metrics: List<PerformanceMetric>,
        state: PerformanceState
    ): List<PerformanceRecommendation> {
        val recommendations = mutableListOf<PerformanceRecommendation>()
        
        // 内存使用过高警告
        if (state.memoryUsage.usagePercentage > 80) {
            recommendations.add(
                PerformanceRecommendation(
                    level = RecommendationLevel.WARNING,
                    category = RecommendationCategory.MEMORY,
                    title = "内存使用过高",
                    description = "当前内存使用率 ${state.memoryUsage.usagePercentage}%，建议优化内存使用",
                    suggestion = "检查内存泄漏，减少大对象创建，及时释放资源"
                )
            )
        }
        
        // CPU使用过高警告
        if (state.cpuUsage.cpuUsagePercentage > 80) {
            recommendations.add(
                PerformanceRecommendation(
                    level = RecommendationLevel.WARNING,
                    category = RecommendationCategory.CPU,
                    title = "CPU使用过高",
                    description = "当前CPU使用率 ${state.cpuUsage.cpuUsagePercentage}%，可能影响应用响应",
                    suggestion = "优化计算密集型操作，使用协程异步处理，减少主线程阻塞"
                )
            )
        }
        
        // 帧率过低警告
        if (state.frameRate < 30) {
            recommendations.add(
                PerformanceRecommendation(
                    level = RecommendationLevel.WARNING,
                    category = RecommendationCategory.UI,
                    title = "帧率过低",
                    description = "当前帧率 ${state.frameRate}fps，可能影响用户体验",
                    suggestion = "优化UI渲染，减少布局层级，使用Compose LazyColumn等高效组件"
                )
            )
        }
        
        // 慢操作警告
        metrics.forEach { metric ->
            if (metric.averageDurationMs > metric.warningThresholdMs) {
                recommendations.add(
                    PerformanceRecommendation(
                        level = RecommendationLevel.INFO,
                        category = RecommendationCategory.PERFORMANCE,
                        title = "慢操作检测",
                        description = "操作 '${metric.name}' 平均耗时 ${metric.averageDurationMs}ms",
                        suggestion = "考虑优化此操作，使用缓存或异步处理"
                    )
                )
            }
        }
        
        return recommendations
    }
    
    /**
     * 操作跟踪器
     */
    class OperationTracker(
        private val operationName: String,
        private val monitor: PerformanceMonitor
    ) {
        private val startTime = SystemClock.elapsedRealtime()
        
        fun stop() {
            val duration = SystemClock.elapsedRealtime() - startTime
            monitor.recordOperation(operationName, duration)
        }
    }
    
    /**
     * 性能指标
     */
    data class PerformanceMetric(
        val name: String,
        val warningThresholdMs: Long = 1000L, // 1秒警告阈值
        private val measurements: MutableList<Long> = mutableListOf(),
        private val timestamps: MutableList<Long> = mutableListOf()
    ) {
        val count: Int get() = measurements.size
        val totalDurationMs: Long get() = measurements.sum()
        val averageDurationMs: Long get() = if (measurements.isEmpty()) 0 else totalDurationMs / count
        val maxDurationMs: Long get() = measurements.maxOrNull() ?: 0
        val minDurationMs: Long get() = measurements.minOrNull() ?: 0
        
        fun record(durationMs: Long) {
            val now = System.currentTimeMillis()
            measurements.add(durationMs)
            timestamps.add(now)
            
            // 保持最近1000个测量值
            if (measurements.size > 1000) {
                measurements.removeAt(0)
                timestamps.removeAt(0)
            }
        }
        
        fun cleanupOldData(thresholdMs: Long) {
            val now = System.currentTimeMillis()
            val indicesToRemove = timestamps.withIndex()
                .filter { (_, timestamp) -> now - timestamp > thresholdMs }
                .map { it.index }
                .reversed()
            
            indicesToRemove.forEach { index ->
                measurements.removeAt(index)
                timestamps.removeAt(index)
            }
        }
        
        fun getRecentMeasurements(count: Int): List<Long> {
            return measurements.takeLast(count)
        }
    }
    
    /**
     * 性能状态
     */
    data class PerformanceState(
        val memoryUsage: MemoryInfo = MemoryInfo(),
        val cpuUsage: CpuInfo = CpuInfo(),
        val frameRate: Int = 60,
        val networkQuality: Int = 100,
        val timestamp: Long = System.currentTimeMillis()
    )
    
    /**
     * 内存信息
     */
    data class MemoryInfo(
        val usedBytes: Long = 0,
        val totalBytes: Long = 0,
        val maxBytes: Long = 0,
        val usagePercentage: Int = 0
    )
    
    /**
     * CPU信息
     */
    data class CpuInfo(
        val processCpuTimeMs: Long = 0,
        val cpuUsagePercentage: Int = 0
    )
    
    /**
     * 性能报告
     */
    data class PerformanceReport(
        val timestamp: Long,
        val metrics: List<PerformanceMetric>,
        val memoryUsage: MemoryInfo,
        val cpuUsage: CpuInfo,
        val frameRate: Int,
        val networkQuality: Int,
        val recommendations: List<PerformanceRecommendation>
    ) {
        val hasWarnings: Boolean
            get() = recommendations.any { it.level == RecommendationLevel.WARNING }
        
        val hasIssues: Boolean
            get() = recommendations.isNotEmpty()
    }
    
    /**
     * 性能建议
     */
    data class PerformanceRecommendation(
        val level: RecommendationLevel,
        val category: RecommendationCategory,
        val title: String,
        val description: String,
        val suggestion: String
    )
    
    /**
     * 建议级别
     */
    enum class RecommendationLevel {
        INFO,       // 信息
        WARNING,    // 警告
        CRITICAL    // 严重
    }
    
    /**
     * 建议类别
     */
    enum class RecommendationCategory {
        MEMORY,     // 内存
        CPU,        // CPU
        UI,         // UI渲染
        NETWORK,    // 网络
        PERFORMANCE // 性能
    }
    
    companion object {
        private val singleton by lazy { PerformanceMonitor() }
        
        @JvmStatic
        fun getInstance(): PerformanceMonitor = singleton
        
        /**
         * 快速记录操作耗时
         */
        @JvmStatic
        fun <T> recordOperation(operationName: String, block: () -> T): T {
            val tracker = singleton.startOperation(operationName)
            return try {
                block()
            } finally {
                tracker.stop()
            }
        }
        
        /**
         * 异步记录操作耗时
         */
        @JvmStatic
        suspend fun <T> recordOperationAsync(operationName: String, block: suspend () -> T): T {
            val tracker = singleton.startOperation(operationName)
            return try {
                block()
            } finally {
                tracker.stop()
            }
        }
    }
}
