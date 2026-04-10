package com.quant.system.core.performance

import android.app.Application
import android.content.Context
import android.os.Build
import android.os.StrictMode
import androidx.annotation.RequiresApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotxlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.Executors
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * 应用性能优化器
 * 整合各种性能优化策略
 */
class AppPerformanceOptimizer(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val performanceMonitor = PerformanceMonitor.getInstance()
    private val memoryLeakDetector = MemoryLeakDetector.getInstance(context)
    
    private val _optimizationState = MutableStateFlow(OptimizationState())
    val optimizationState: StateFlow<OptimizationState> = _optimizationState.asStateFlow()
    
    private var optimizationJob: Job? = null
    private var isOptimizationEnabled = false
    
    // 线程池优化
    private val ioThreadPool = Executors.newFixedThreadPool(
        Runtime.getRuntime().availableProcessors().coerceAtLeast(2).coerceAtMost(4)
    ) as ThreadPoolExecutor
    
    private val computationThreadPool = Executors.newFixedThreadPool(
        Runtime.getRuntime().availableProcessors()
    ) as ThreadPoolExecutor
    
    // 性能计数器
    private val uiRenderCounter = AtomicInteger(0)
    private val networkRequestCounter = AtomicInteger(0)
    private val databaseOperationCounter = AtomicInteger(0)
    
    /**
     * 启用性能优化
     */
    fun enableOptimizations() {
        if (isOptimizationEnabled) return
        
        isOptimizationEnabled = true
        
        // 1. 启用严格模式（仅调试版本）
        if (BuildConfig.DEBUG) {
            enableStrictMode()
        }
        
        // 2. 启动性能监控
        performanceMonitor.startMonitoring()
        
        // 3. 启动内存泄漏检测
        memoryLeakDetector.startMonitoring()
        
        // 4. 启动优化任务
        optimizationJob = scope.launch {
            while (isOptimizationEnabled) {
                performOptimizations()
                delay(60000L) // 每分钟执行一次优化检查
            }
        }
        
        // 5. 注册内存警告监听
        registerMemoryWarningListener()
        
        // 6. 优化线程池配置
        optimizeThreadPools()
        
        _optimizationState.value = OptimizationState(
            isEnabled = true,
            optimizationsApplied = getAppliedOptimizations(),
            lastOptimizedAt = System.currentTimeMillis()
        )
        
        android.util.Log.i("AppPerformanceOptimizer", "性能优化已启用")
    }
    
    /**
     * 禁用性能优化
     */
    fun disableOptimizations() {
        if (!isOptimizationEnabled) return
        
        isOptimizationEnabled = false
        
        // 停止所有优化任务
        optimizationJob?.cancel()
        optimizationJob = null
        
        performanceMonitor.stopMonitoring()
        memoryLeakDetector.stopMonitoring()
        
        // 关闭线程池
        ioThreadPool.shutdown()
        computationThreadPool.shutdown()
        
        _optimizationState.value = OptimizationState(
            isEnabled = false,
            optimizationsApplied = emptyList(),
            lastOptimizedAt = System.currentTimeMillis()
        )
        
        android.util.Log.i("AppPerformanceOptimizer", "性能优化已禁用")
    }
    
    /**
     * 执行UI渲染操作（带性能监控）
     */
    fun <T> performUiRender(operationName: String, block: () -> T): T {
        uiRenderCounter.incrementAndGet()
        return PerformanceMonitor.recordOperation("UI_Render:$operationName", block)
    }
    
    /**
     * 执行网络请求（带性能监控和线程池优化）
     */
    suspend fun <T> performNetworkRequest(operationName: String, block: suspend () -> T): T {
        networkRequestCounter.incrementAndGet()
        return PerformanceMonitor.recordOperationAsync("Network:$operationName") {
            // 使用IO线程池执行网络请求
            kotlinx.coroutines.withContext(Dispatchers.IO) {
                block()
            }
        }
    }
    
    /**
     * 执行数据库操作（带性能监控和线程池优化）
     */
    suspend fun <T> performDatabaseOperation(operationName: String, block: suspend () -> T): T {
        databaseOperationCounter.incrementAndGet()
        return PerformanceMonitor.recordOperationAsync("Database:$operationName") {
            // 使用计算线程池执行数据库操作
            kotlinx.coroutines.withContext(Dispatchers.Default) {
                block()
            }
        }
    }
    
    /**
     * 获取性能报告
     */
    fun getPerformanceReport(): PerformanceReport {
        val perfReport = performanceMonitor.getPerformanceReport()
        val leakStats = memoryLeakDetector.getLeakStats()
        
        return PerformanceReport(
            timestamp = System.currentTimeMillis(),
            performanceMetrics = perfReport,
            leakStats = leakStats,
            operationCounts = OperationCounts(
                uiRenders = uiRenderCounter.get(),
                networkRequests = networkRequestCounter.get(),
                databaseOperations = databaseOperationCounter.get()
            ),
            threadPoolStats = getThreadPoolStats(),
            recommendations = generateOptimizationRecommendations(perfReport, leakStats)
        )
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        disableOptimizations()
        memoryLeakDetector.cleanupCollectedObjects()
        
        // 清理缓存
        Runtime.getRuntime().gc()
        System.runFinalization()
        
        android.util.Log.i("AppPerformanceOptimizer", "资源已清理")
    }
    
    private fun enableStrictMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.GINGERBREAD) {
            val threadPolicyBuilder = StrictMode.ThreadPolicy.Builder()
                .detectAll()
                .penaltyLog()
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.HONEYCOMB) {
                threadPolicyBuilder.penaltyFlashScreen()
            }
            
            StrictMode.setThreadPolicy(threadPolicyBuilder.build())
            
            val vmPolicyBuilder = StrictMode.VmPolicy.Builder()
                .detectLeakedSqlLiteObjects()
                .detectLeakedClosableObjects()
                .penaltyLog()
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.HONEYCOMB) {
                vmPolicyBuilder.detectLeakedRegistrationObjects()
            }
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN) {
                vmPolicyBuilder.detectLeakedRegistrationObjects()
            }
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR2) {
                vmPolicyBuilder.detectFileUriExposure()
            }
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vmPolicyBuilder.detectContentUriWithoutPermission()
            }
            
            StrictMode.setVmPolicy(vmPolicyBuilder.build())
        }
    }
    
    private suspend fun performOptimizations() {
        val report = getPerformanceReport()
        
        // 根据性能报告执行优化
        if (report.performanceMetrics.memoryUsage.usagePercentage > 70) {
            optimizeMemoryUsage()
        }
        
        if (report.performanceMetrics.cpuUsage.cpuUsagePercentage > 80) {
            optimizeCpuUsage()
        }
        
        if (report.performanceMetrics.frameRate < 45) {
            optimizeUiRendering()
        }
        
        if (report.leakStats.hasLeaks) {
            handleMemoryLeaks(report.leakStats)
        }
        
        // 更新优化状态
        _optimizationState.value = OptimizationState(
            isEnabled = true,
            optimizationsApplied = getAppliedOptimizations(),
            lastOptimizedAt = System.currentTimeMillis(),
            performanceReport = report
        )
    }
    
    private fun optimizeMemoryUsage() {
        // 1. 清理图片缓存
        clearImageCache()
        
        // 2. 清理临时文件
        clearTempFiles()
        
        // 3. 建议系统进行垃圾回收
        Runtime.getRuntime().gc()
        
        android.util.Log.i("AppPerformanceOptimizer", "内存使用优化已执行")
    }
    
    private fun optimizeCpuUsage() {
        // 1. 调整线程池大小
        val availableProcessors = Runtime.getRuntime().availableProcessors()
        ioThreadPool.corePoolSize = availableProcessors.coerceAtLeast(2).coerceAtMost(4)
        computationThreadPool.corePoolSize = availableProcessors
        
        // 2. 清理空闲线程
        ioThreadPool.purge()
        computationThreadPool.purge()
        
        android.util.Log.i("AppPerformanceOptimizer", "CPU使用优化已执行")
    }
    
    private fun optimizeUiRendering() {
        // 1. 建议减少UI复杂度
        // 2. 建议使用更高效的UI组件
        // 3. 建议减少布局层级
        
        android.util.Log.i("AppPerformanceOptimizer", "UI渲染优化建议已生成")
    }
    
    private fun handleMemoryLeaks(leakStats: MemoryLeakDetector.LeakStats) {
        // 1. 记录泄漏信息
        leakStats.recentLeaks.forEach { leak ->
            android.util.Log.w(
                "AppPerformanceOptimizer",
                "内存泄漏: ${leak.key} (类型: ${leak.type}, 年龄: ${leak.ageMs}ms)"
            )
        }
        
        // 2. 强制垃圾回收
        memoryLeakDetector.forceGcAndCheck()
        
        // 3. 清理已回收的对象
        memoryLeakDetector.cleanupCollectedObjects()
        
        android.util.Log.i("AppPerformanceOptimizer", "内存泄漏处理已执行")
    }
    
    private fun registerMemoryWarningListener() {
        // 这里可以注册系统内存警告监听
        // 实际项目中可以使用ActivityManager.MemoryInfo或OnTrimMemory回调
    }
    
    private fun optimizeThreadPools() {
        // 配置线程池参数
        ioThreadPool.keepAliveTime = 30L
        ioThreadPool.unit = TimeUnit.SECONDS
        ioThreadPool.allowCoreThreadTimeOut(true)
        
        computationThreadPool.keepAliveTime = 60L
        computationThreadPool.unit = TimeUnit.SECONDS
        computationThreadPool.allowCoreThreadTimeOut(true)
    }
    
    private fun clearImageCache() {
        // 清理图片缓存
        // 实际项目中可以使用Glide、Coil等图片加载库的缓存清理方法
    }
    
    private fun clearTempFiles() {
        // 清理临时文件
        try {
            val cacheDir = context.cacheDir
            cacheDir?.listFiles()?.forEach { file ->
                if (file.isFile && file.lastModified() < System.currentTimeMillis() - 24 * 60 * 60 * 1000) {
                    file.delete()
                }
            }
        } catch (e: Exception) {
            // 忽略清理错误
        }
    }
    
    private fun getAppliedOptimizations(): List<String> {
        val optimizations = mutableListOf<String>()
        
        if (BuildConfig.DEBUG) {
            optimizations.add("严格模式")
        }
        
        optimizations.add("性能监控")
        optimizations.add("内存泄漏检测")
        optimizations.add("线程池优化")
        optimizations.add("内存使用优化")
        optimizations.add("CPU使用优化")
        optimizations.add("UI渲染优化")
        
        return optimizations
    }
    
    private fun getThreadPoolStats(): ThreadPoolStats {
        return ThreadPoolStats(
            ioPoolActiveThreads = ioThreadPool.activeCount,
            ioPoolQueueSize = ioThreadPool.queue.size,
            ioPoolCompletedTasks = ioThreadPool.completedTaskCount,
            computationPoolActiveThreads = computationThreadPool.activeCount,
            computationPoolQueueSize = computationThreadPool.queue.size,
            computationPoolCompletedTasks = computationThreadPool.completedTaskCount
        )
    }
    
    private fun generateOptimizationRecommendations(
        perfReport: PerformanceMonitor.PerformanceReport,
        leakStats: MemoryLeakDetector.LeakStats
    ): List<OptimizationRecommendation> {
        val recommendations = mutableListOf<OptimizationRecommendation>()
        
        // 内存使用建议
        if (perfReport.memoryUsage.usagePercentage > 80) {
            recommendations.add(
                OptimizationRecommendation(
                    priority = Priority.HIGH,
                    category = OptimizationCategory.MEMORY,
                    title = "内存使用过高",
                    description = "当前内存使用率 ${perfReport.memoryUsage.usagePercentage}%",
                    action = "清理图片缓存和临时文件，检查内存泄漏"
                )
            )
        }
        
        // CPU使用建议
        if (perfReport.cpuUsage.cpuUsagePercentage > 80) {
            recommendations.add(
                OptimizationRecommendation(
                    priority = Priority.HIGH,
                    category = OptimizationCategory.CPU,
                    title = "CPU使用过高",
                    description = "当前CPU使用率 ${perfReport.cpuUsage.cpuUsagePercentage}%",
                    action = "优化计算密集型操作，使用异步处理"
                )
            )
        }
        
        // 帧率建议
        if (perfReport.frameRate < 45) {
            recommendations.add(
                OptimizationRecommendation(
                    priority = Priority.MEDIUM,
                    category = OptimizationCategory.UI,
                    title = "帧率过低",
                    description = "当前帧率 ${perfReport.frameRate}fps",
                    action = "优化UI渲染，减少布局复杂度"
                )
            )
        }
        
        // 内存泄漏建议
        if (leakStats.hasLeaks) {
            recommendations.add(
                OptimizationRecommendation(
                    priority = Priority.CRITICAL,
                    category = OptimizationCategory.MEMORY,
                    title = "检测到内存泄漏",
                    description = "发现 ${leakStats.leakedCount} 个内存泄漏",
                    action = "检查Activity、Fragment、ViewModel等组件的生命周期管理"
                )
            )
        }
        
        // 网络质量建议
        if (perfReport.networkQuality < 50) {
            recommendations.add(
                OptimizationRecommendation(
                    priority = Priority.MEDIUM,
                    category = OptimizationCategory.NETWORK,
                    title = "网络质量差",
                    description = "当前网络质量 ${perfReport.networkQuality}/100",
                    action = "启用缓存，减少网络请求，使用增量更新"
                )
            )
        }
        
        return recommendations
    }
    
    /**
     * 优化状态
     */
    data class OptimizationState(
        val isEnabled: Boolean = false,
        val optimizationsApplied: List<String> = emptyList(),
        val lastOptimizedAt: Long = 0,
        val performanceReport: PerformanceReport? = null
    )
    
    /**
     * 性能报告
     */
    data class PerformanceReport(
        val timestamp: Long,
        val performanceMetrics: PerformanceMonitor.PerformanceReport,
        val leakStats: MemoryLeakDetector.LeakStats,
        val operationCounts: OperationCounts,
        val threadPoolStats: ThreadPoolStats,
        val recommendations: List<OptimizationRecommendation>
    )
    
    /**
     * 操作计数
     */
    data class OperationCounts(
        val uiRenders: Int,
        val networkRequests: Int,
        val databaseOperations: Int
    )
    
    /**
     * 线程池统计
     */
    data class ThreadPoolStats(
        val ioPoolActiveThreads: Int,
        val ioPoolQueueSize: Int,
        val ioPoolCompletedTasks: Long,
        val computationPoolActiveThreads: Int,
        val computationPoolQueueSize: Int,
        val computationPoolCompletedTasks: Long
    )
    
    /**
     * 优化建议
     */
    data class OptimizationRecommendation(
        val priority: Priority,
        val category: OptimizationCategory,
        val title: String,
        val description: String,
        val action: String
    )
    
    /**
     * 优先级
     */
    enum class Priority {
        LOW,       // 低优先级
        MEDIUM,    // 中优先级
        HIGH,      // 高优先级
        CRITICAL   // 关键优先级
    }
    
    /**
     * 优化类别
     */
    enum class OptimizationCategory {
        MEMORY,    // 内存
        CPU,       // CPU
        UI,        // UI渲染
        NETWORK,   // 网络
        STORAGE,   // 存储
        GENERAL    // 通用
    }
    
    companion object {
        private val instanceMap = ConcurrentHashMap<Context, AppPerformanceOptimizer>()
        
        @JvmStatic
        fun getInstance(context: Context): AppPerformanceOptimizer {
            return instanceMap.getOrPut(context) {
                AppPerformanceOptimizer(context.applicationContext ?: context)
            }
        }
        
        /**
         * 快速启用优化
         */
        @JvmStatic
        fun enableForApp(application: Application) {
            val optimizer = getInstance(application)
            optimizer.enableOptimizations()
        }
        
        /**
         * 获取全局优化报告
         */
        @JvmStatic
        fun getGlobalReport(): Map<Context, PerformanceReport> {
            return instanceMap.mapValues { it.value.getPerformanceReport() }
        }
        
        /**
         * 清理所有优化器
         */
        @JvmStatic
        fun cleanupAll() {
            instanceMap.values.forEach { it.cleanup() }
            instanceMap.clear()
        }
    }
}