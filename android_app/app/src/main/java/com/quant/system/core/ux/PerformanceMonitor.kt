package com.quant.system.core.ux

import android.content.Context
import android.os.Build
import android.os.Debug
import android.os.Process
import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * 性能监控和用户体验分析工具
 * 监控应用性能指标，分析用户体验问题
 */
class PerformanceMonitor(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val performanceData = ConcurrentHashMap<String, PerformanceMetric>()
    private val uiRenderTimes = ConcurrentHashMap<String, MutableList<Long>>()
    private val networkRequestTimes = ConcurrentHashMap<String, MutableList<Long>>()
    private val userInteractions = ConcurrentHashMap<String, AtomicInteger>()
    private val errorCounts = ConcurrentHashMap<String, AtomicInteger>()
    
    private var monitoringJob: Job? = null
    private var isMonitoring = false
    
    /**
     * 开始监控
     */
    fun startMonitoring(intervalMs: Long = 5000L) {
        if (isMonitoring) return
        
        isMonitoring = true
        monitoringJob = scope.launch {
            while (isMonitoring) {
                collectPerformanceMetrics()
                analyzePerformanceData()
                delay(intervalMs)
            }
        }
        
        Log.i(TAG, "性能监控已启动，间隔: ${intervalMs}ms")
    }
    
    /**
     * 停止监控
     */
    fun stopMonitoring() {
        isMonitoring = false
        monitoringJob?.cancel()
        monitoringJob = null
        
        Log.i(TAG, "性能监控已停止")
    }
    
    /**
     * 记录UI渲染时间
     */
    fun recordUIRenderTime(screenName: String, renderTimeMs: Long) {
        val times = uiRenderTimes.getOrPut(screenName) { mutableListOf() }
        times.add(renderTimeMs)
        
        // 保持最近100个记录
        if (times.size > 100) {
            times.removeAt(0)
        }
        
        // 更新性能指标
        val metric = performanceData.getOrPut("ui_render_$screenName") {
            PerformanceMetric("ui_render_$screenName", "UI渲染时间: $screenName")
        }
        metric.addSample(renderTimeMs.toDouble())
        
        Log.d(TAG, "UI渲染时间记录: $screenName - ${renderTimeMs}ms")
    }
    
    /**
     * 记录网络请求时间
     */
    fun recordNetworkRequestTime(endpoint: String, requestTimeMs: Long) {
        val times = networkRequestTimes.getOrPut(endpoint) { mutableListOf() }
        times.add(requestTimeMs)
        
        // 保持最近50个记录
        if (times.size > 50) {
            times.removeAt(0)
        }
        
        // 更新性能指标
        val metric = performanceData.getOrPut("network_$endpoint") {
            PerformanceMetric("network_$endpoint", "网络请求: $endpoint")
        }
        metric.addSample(requestTimeMs.toDouble())
        
        Log.d(TAG, "网络请求时间记录: $endpoint - ${requestTimeMs}ms")
    }
    
    /**
     * 记录用户交互
     */
    fun recordUserInteraction(interactionType: String) {
        val count = userInteractions.getOrPut(interactionType) { AtomicInteger(0) }
        count.incrementAndGet()
        
        Log.d(TAG, "用户交互记录: $interactionType")
    }
    
    /**
     * 记录错误
     */
    fun recordError(errorType: String) {
        val count = errorCounts.getOrPut(errorType) { AtomicInteger(0) }
        count.incrementAndGet()
        
        Log.d(TAG, "错误记录: $errorType")
    }
    
    /**
     * 记录操作性能
     */
    fun recordOperationPerformance(operationName: String, durationMs: Long) {
        val metric = performanceData.getOrPut("operation_$operationName") {
            PerformanceMetric("operation_$operationName", "操作性能: $operationName")
        }
        metric.addSample(durationMs.toDouble())
        
        Log.d(TAG, "操作性能记录: $operationName - ${durationMs}ms")
    }
    
    /**
     * 获取性能报告
     */
    suspend fun getPerformanceReport(): PerformanceReport {
        return withContext(Dispatchers.IO) {
            val metrics = performanceData.values.toList()
            val uiPerformance = analyzeUIPerformance()
            val networkPerformance = analyzeNetworkPerformance()
            val memoryUsage = getMemoryUsage()
            val cpuUsage = getCpuUsage()
            val batteryUsage = getBatteryUsage()
            val thermalState = getThermalState()
            
            PerformanceReport(
                timestamp = System.currentTimeMillis(),
                metrics = metrics,
                uiPerformance = uiPerformance,
                networkPerformance = networkPerformance,
                memoryUsage = memoryUsage,
                cpuUsage = cpuUsage,
                batteryUsage = batteryUsage,
                thermalState = thermalState,
                userInteractions = userInteractions.mapValues { it.value.get() },
                errorCounts = errorCounts.mapValues { it.value.get() },
                recommendations = generateRecommendations()
            )
        }
    }
    
    /**
     * 获取实时性能指标
     */
    fun getRealTimeMetrics(): Map<String, Double> {
        return performanceData.mapValues { it.value.currentValue }
    }
    
    /**
     * 重置监控数据
     */
    fun resetData() {
        performanceData.clear()
        uiRenderTimes.clear()
        networkRequestTimes.clear()
        userInteractions.clear()
        errorCounts.clear()
        
        Log.i(TAG, "性能监控数据已重置")
    }
    
    /**
     * 导出性能数据到文件
     */
    suspend fun exportDataToFile(): File {
        return withContext(Dispatchers.IO) {
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val fileName = "performance_report_$timestamp.json"
            val file = File(context.filesDir, fileName)
            
            val report = getPerformanceReport()
            val jsonString = report.toString()
            
            file.writeText(jsonString)
            
            Log.i(TAG, "性能数据已导出到: ${file.absolutePath}")
            file
        }
    }
    
    private fun collectPerformanceMetrics() {
        try {
            // 收集内存使用情况
            val memoryMetric = performanceData.getOrPut("memory_usage") {
                PerformanceMetric("memory_usage", "内存使用")
            }
            val memoryUsage = getMemoryUsage()
            memoryMetric.addSample(memoryUsage.usedMemoryMB.toDouble())
            
            // 收集CPU使用情况
            val cpuMetric = performanceData.getOrPut("cpu_usage") {
                PerformanceMetric("cpu_usage", "CPU使用率")
            }
            val cpuUsage = getCpuUsage()
            cpuMetric.addSample(cpuUsage.toDouble())
            
            // 收集电池使用情况
            val batteryMetric = performanceData.getOrPut("battery_usage") {
                PerformanceMetric("battery_usage", "电池使用")
            }
            val batteryUsage = getBatteryUsage()
            batteryMetric.addSample(batteryUsage.toDouble())
            
            // 收集帧率（如果可用）
            collectFrameRate()
            
            Log.d(TAG, "性能指标已收集: 内存=${memoryUsage.usedMemoryMB}MB, CPU=${cpuUsage}%, 电池=${batteryUsage}%")
        } catch (e: Exception) {
            Log.e(TAG, "收集性能指标失败", e)
        }
    }
    
    private fun collectFrameRate() {
        // 在实际项目中，这里应该从Choreographer或FrameMetrics获取帧率
        // 这里简化实现，使用模拟数据
        val frameRate = 60.0 // 假设帧率为60fps
        val metric = performanceData.getOrPut("frame_rate") {
            PerformanceMetric("frame_rate", "帧率")
        }
        metric.addSample(frameRate)
    }
    
    private fun analyzePerformanceData() {
        // 分析性能数据，检测性能问题
        performanceData.values.forEach { metric ->
            if (metric.sampleCount >= 10) {
                val avg = metric.average
                val stdDev = metric.standardDeviation
                
                // 检测异常值
                if (stdDev > avg * 0.5) {
                    Log.w(TAG, "性能指标波动较大: ${metric.name}, 平均值=${avg}, 标准差=${stdDev}")
                }
                
                // 检测性能下降
                if (metric.trend == PerformanceMetric.Trend.DECREASING) {
                    Log.w(TAG, "性能下降检测: ${metric.name}, 趋势=${metric.trend}")
                }
            }
        }
    }
    
    private fun analyzeUIPerformance(): UIPerformance {
        val screenMetrics = uiRenderTimes.map { (screenName, times) ->
            if (times.isNotEmpty()) {
                val avg = times.average()
                val max = (times.maxOrNull() ?: 0L).toDouble()
                val min = (times.minOrNull() ?: 0L).toDouble()
                val p95 = times.sorted().let { sorted ->
                    val index = (sorted.size * 0.95).toInt()
                    sorted[index].toDouble()
                }
                
                ScreenPerformance(
                    screenName = screenName,
                    averageRenderTime = avg,
                    maxRenderTime = max,
                    minRenderTime = min,
                    p95RenderTime = p95,
                    sampleCount = times.size
                )
            } else {
                null
            }
        }.filterNotNull()
        
        val overallAvg = screenMetrics.map { it.averageRenderTime }.average()
        val overallMax = screenMetrics.map { it.maxRenderTime }.maxOrNull() ?: 0.0
        val overallMin = screenMetrics.map { it.minRenderTime }.minOrNull() ?: 0.0
        
        return UIPerformance(
            screenMetrics = screenMetrics,
            overallAverage = overallAvg,
            overallMaximum = overallMax,
            overallMinimum = overallMin,
            totalSamples = screenMetrics.sumOf { it.sampleCount }
        )
    }
    
    private fun analyzeNetworkPerformance(): NetworkPerformance {
        val endpointMetrics = networkRequestTimes.map { (endpoint, times) ->
            if (times.isNotEmpty()) {
                val avg = times.average()
                val max = (times.maxOrNull() ?: 0L).toDouble()
                val min = (times.minOrNull() ?: 0L).toDouble()
                val p95 = times.sorted().let { sorted ->
                    val index = (sorted.size * 0.95).toInt()
                    sorted[index].toDouble()
                }
                val successRate = 0.95 // 假设成功率为95%
                
                EndpointPerformance(
                    endpoint = endpoint,
                    averageResponseTime = avg,
                    maxResponseTime = max,
                    minResponseTime = min,
                    p95ResponseTime = p95,
                    successRate = successRate,
                    sampleCount = times.size
                )
            } else {
                null
            }
        }.filterNotNull()
        
        val overallAvg = endpointMetrics.map { it.averageResponseTime }.average()
        val overallMax = endpointMetrics.map { it.maxResponseTime }.maxOrNull() ?: 0.0
        val overallMin = endpointMetrics.map { it.minResponseTime }.minOrNull() ?: 0.0
        val overallSuccessRate = endpointMetrics.map { it.successRate }.average()
        
        return NetworkPerformance(
            endpointMetrics = endpointMetrics,
            overallAverage = overallAvg,
            overallMaximum = overallMax,
            overallMinimum = overallMin,
            overallSuccessRate = overallSuccessRate,
            totalRequests = endpointMetrics.sumOf { it.sampleCount }
        )
    }
    
    private fun getMemoryUsage(): MemoryUsage {
        return try {
            val runtime = Runtime.getRuntime()
            val totalMemory = runtime.totalMemory() / (1024 * 1024) // MB
            val freeMemory = runtime.freeMemory() / (1024 * 1024) // MB
            val usedMemory = totalMemory - freeMemory
            
            // 获取Native内存使用（如果可用）
            val nativeHeapSize = Debug.getNativeHeapSize() / (1024 * 1024) // MB
            val nativeHeapAllocated = Debug.getNativeHeapAllocatedSize() / (1024 * 1024) // MB
            val nativeHeapFree = Debug.getNativeHeapFreeSize() / (1024 * 1024) // MB
            
            MemoryUsage(
                totalMemoryMB = totalMemory,
                usedMemoryMB = usedMemory,
                freeMemoryMB = freeMemory,
                nativeHeapSizeMB = nativeHeapSize,
                nativeHeapAllocatedMB = nativeHeapAllocated,
                nativeHeapFreeMB = nativeHeapFree,
                memoryUsagePercentage = (usedMemory.toDouble() / totalMemory.toDouble()) * 100
            )
        } catch (e: Exception) {
            Log.e(TAG, "获取内存使用失败", e)
            MemoryUsage()
        }
    }
    
    private fun getCpuUsage(): Double {
        return try {
            // 读取/proc/stat获取CPU使用率
            val statFile = File("/proc/stat")
            if (statFile.exists()) {
                val reader = BufferedReader(FileReader(statFile))
                val firstLine = reader.readLine()
                reader.close()
                
                if (firstLine.startsWith("cpu ")) {
                    val parts = firstLine.split("\\s+".toRegex())
                    if (parts.size >= 8) {
                        val user = parts[1].toLong()
                        val nice = parts[2].toLong()
                        val system = parts[3].toLong()
                        val idle = parts[4].toLong()
                        val iowait = parts[5].toLong()
                        val irq = parts[6].toLong()
                        val softirq = parts[7].toLong()
                        
                        val total = user + nice + system + idle + iowait + irq + softirq
                        val used = total - idle
                        
                        return (used.toDouble() / total.toDouble()) * 100
                    }
                }
            }
            0.0
        } catch (e: Exception) {
            Log.e(TAG, "获取CPU使用率失败", e)
            0.0
        }
    }
    
    private fun getBatteryUsage(): Double {
        return try {
            // 在实际项目中，这里应该从BatteryManager获取电池信息
            // 这里简化实现，返回固定值
            50.0
        } catch (e: Exception) {
            Log.e(TAG, "获取电池使用率失败", e)
            0.0
        }
    }
    
    private fun getThermalState(): String {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val powerManager = context.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
                val thermalStatus = powerManager.currentThermalStatus
                
                when (thermalStatus) {
                    android.os.PowerManager.THERMAL_STATUS_NONE -> "正常"
                    android.os.PowerManager.THERMAL_STATUS_LIGHT -> "轻度"
                    android.os.PowerManager.THERMAL_STATUS_MODERATE -> "中度"
                    android.os.PowerManager.THERMAL_STATUS_SEVERE -> "严重"
                    android.os.PowerManager.THERMAL_STATUS_CRITICAL -> "临界"
                    android.os.PowerManager.THERMAL_STATUS_EMERGENCY -> "紧急"
                    android.os.PowerManager.THERMAL_STATUS_SHUTDOWN -> "关机"
                    else -> "未知"
                }
            } else {
                "未知"
            }
        } catch (e: Exception) {
            Log.e(TAG, "获取热状态失败", e)
            "未知"
        }
    }
    
    private fun generateRecommendations(): List<PerformanceRecommendation> {
        val recommendations = mutableListOf<PerformanceRecommendation>()
        
        // 分析UI性能
        val uiPerformance = analyzeUIPerformance()
        if (uiPerformance.overallAverage > 16.0) { // 超过16ms（60fps的帧时间）
            recommendations.add(
                PerformanceRecommendation(
                    category = "UI性能",
                    severity = "高",
                    description = "UI渲染时间过长，可能影响用户体验",
                    suggestion = "优化Compose重组，减少不必要的状态更新，使用remember和derivedStateOf",
                    impact = "高"
                )
            )
        }
        
        // 分析网络性能
        val networkPerformance = analyzeNetworkPerformance()
        if (networkPerformance.overallAverage > 1000.0) { // 超过1秒
            recommendations.add(
                PerformanceRecommendation(
                    category = "网络性能",
                    severity = "中",
                    description = "网络请求响应时间过长",
                    suggestion = "优化API调用，使用缓存，减少请求数据量",
                    impact = "中"
                )
            )
        }
        
        // 分析内存使用
        val memoryUsage = getMemoryUsage()
        if (memoryUsage.memoryUsagePercentage > 80.0) { // 内存使用率超过80%
            recommendations.add(
                PerformanceRecommendation(
                    category = "内存使用",
                    severity = "高",
                    description = "内存使用率过高，可能导致OOM",
                    suggestion = "检查内存泄漏，优化图片加载，使用内存缓存",
                    impact = "高"
                )
            )
        }
        
        // 分析CPU使用
        val cpuUsage = getCpuUsage()
        if (cpuUsage > 80.0) { // CPU使用率超过80%
            recommendations.add(
                PerformanceRecommendation(
                    category = "CPU使用",
                    severity = "中",
                    description = "CPU使用率过高，可能导致设备发热",
                    suggestion = "优化计算密集型操作，使用协程调度到IO线程",
                    impact = "中"
                )
            )
        }
        
        // 分析错误率
        val totalErrors = errorCounts.values.sumOf { it.get() }
        val totalInteractions = userInteractions.values.sumOf { it.get() }
        if (totalInteractions > 0) {
            val errorRate = totalErrors.toDouble() / totalInteractions.toDouble()
            if (errorRate > 0.01) { // 错误率超过1%
                recommendations.add(
                    PerformanceRecommendation(
                        category = "错误处理",
                        severity = "高",
                        description = "用户交互错误率过高",
                        suggestion = "加强错误处理，提供更好的用户反馈，优化异常恢复",
                        impact = "高"
                    )
                )
            }
        }
        
        return recommendations
    }
    
    companion object {
        private const val TAG = "PerformanceMonitor"
        
        @Composable
        fun rememberPerformanceMonitor(): PerformanceMonitor {
            val context = LocalContext.current
            return remember {
                PerformanceMonitor(context)
            }
        }
    }
}

/**
 * 性能指标
 */
data class PerformanceMetric(
    val id: String,
    val name: String,
    val unit: String = "",
    private val samples: MutableList<Double> = mutableListOf(),
    val maxSamples: Int = 1000
) {
    var currentValue: Double = 0.0
        private set
    
    val sampleCount: Int
        get() = samples.size
    
    val average: Double
        get() = if (samples.isNotEmpty()) samples.average() else 0.0
    
    val maximum: Double
        get() = if (samples.isNotEmpty()) samples.max() else 0.0
    
    val minimum: Double
        get() = if (samples.isNotEmpty()) samples.min() else 0.0
    
    val standardDeviation: Double
        get() {
            if (samples.size < 2) return 0.0
            val mean = average
            val variance = samples.map { (it - mean) * (it - mean) }.average()
            return kotlin.math.sqrt(variance)
        }
    
    val trend: Trend
        get() {
            if (samples.size < 10) return Trend.STABLE
            
            val recent = samples.takeLast(10)
            val older = samples.take(10)
            
            if (recent.size < 10 || older.size < 10) return Trend.STABLE
            
            val recentAvg = recent.average()
            val olderAvg = older.average()
            
            return when {
                recentAvg > olderAvg * 1.1 -> Trend.INCREASING
                recentAvg < olderAvg * 0.9 -> Trend.DECREASING
                else -> Trend.STABLE
            }
        }
    
    fun addSample(value: Double) {
        samples.add(value)
        currentValue = value
        
        // 保持样本数量不超过最大值
        if (samples.size > maxSamples) {
            samples.removeAt(0)
        }
    }
    
    fun clearSamples() {
        samples.clear()
        currentValue = 0.0
    }
    
    enum class Trend {
        INCREASING, DECREASING, STABLE
    }
}

/**
 * 屏幕性能
 */
data class ScreenPerformance(
    val screenName: String,
    val averageRenderTime: Double,
    val maxRenderTime: Double,
    val minRenderTime: Double,
    val p95RenderTime: Double,
    val sampleCount: Int
)

/**
 * 端点性能
 */
data class EndpointPerformance(
    val endpoint: String,
    val averageResponseTime: Double,
    val maxResponseTime: Double,
    val minResponseTime: Double,
    val p95ResponseTime: Double,
    val successRate: Double,
    val sampleCount: Int
)

/**
 * UI性能
 */
data class UIPerformance(
    val screenMetrics: List<ScreenPerformance>,
    val overallAverage: Double,
    val overallMaximum: Double,
    val overallMinimum: Double,
    val totalSamples: Int
)

/**
 * 网络性能
 */
data class NetworkPerformance(
    val endpointMetrics: List<EndpointPerformance>,
    val overallAverage: Double,
    val overallMaximum: Double,
    val overallMinimum: Double,
    val overallSuccessRate: Double,
    val totalRequests: Int
)

/**
 * 内存使用
 */
data class MemoryUsage(
    val totalMemoryMB: Long = 0,
    val usedMemoryMB: Long = 0,
    val freeMemoryMB: Long = 0,
    val nativeHeapSizeMB: Long = 0,
    val nativeHeapAllocatedMB: Long = 0,
    val nativeHeapFreeMB: Long = 0,
    val memoryUsagePercentage: Double = 0.0
)

/**
 * 性能报告
 */
data class PerformanceReport(
    val timestamp: Long,
    val metrics: List<PerformanceMetric>,
    val uiPerformance: UIPerformance,
    val networkPerformance: NetworkPerformance,
    val memoryUsage: MemoryUsage,
    val cpuUsage: Double,
    val batteryUsage: Double,
    val thermalState: String,
    val userInteractions: Map<String, Int>,
    val errorCounts: Map<String, Int>,
    val recommendations: List<PerformanceRecommendation>
) {
    val formattedTimestamp: String
        get() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(timestamp))
}

/**
 * 性能建议
 */
data class PerformanceRecommendation(
    val category: String,
    val severity: String, // 低、中、高
    val description: String,
    val suggestion: String,
    val impact: String // 低、中、高
)

@Composable
fun rememberPerformanceMonitor(): PerformanceMonitor = PerformanceMonitor.rememberPerformanceMonitor()

/**
 * 性能监控Composable
 */
@Composable
fun PerformanceMonitorComposable(
    monitor: PerformanceMonitor = rememberPerformanceMonitor(),
    enabled: Boolean = true,
    intervalMs: Long = 5000L
) {
    LaunchedEffect(enabled) {
        if (enabled) {
            monitor.startMonitoring(intervalMs)
        } else {
            monitor.stopMonitoring()
        }
    }
    
    // 清理效果
    DisposableEffect(Unit) {
        onDispose {
            monitor.stopMonitoring()
        }
    }
}

/**
 * 记录UI渲染时间的Composable
 */
@Composable
fun MeasureUIRenderTime(
    screenName: String,
    monitor: PerformanceMonitor = rememberPerformanceMonitor(),
    content: @Composable () -> Unit
) {
    val startTime = remember { SystemClock.elapsedRealtime() }
    
    content()
    
    LaunchedEffect(Unit) {
        val endTime = SystemClock.elapsedRealtime()
        val renderTime = endTime - startTime
        monitor.recordUIRenderTime(screenName, renderTime)
    }
}
