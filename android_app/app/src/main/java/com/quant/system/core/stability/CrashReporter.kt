package com.quant.system.core.stability

import android.content.Context
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger

/**
 * 崩溃报告器
 * 收集、存储和上报崩溃信息
 */
class CrashReporter(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val json = Json { prettyPrint = true }
    
    private val crashQueue = ConcurrentLinkedQueue<GlobalExceptionHandler.CrashInfo>()
    private val isReporting = AtomicInteger(0)
    private val maxCrashFiles = 50 // 最大崩溃文件数
    private val maxCrashSize = 10 * 1024 * 1024 // 最大崩溃文件大小：10MB
    
    /**
     * 记录崩溃信息
     */
    fun recordCrash(crashInfo: GlobalExceptionHandler.CrashInfo) {
        scope.launch {
            try {
                // 1. 保存到本地文件
                saveCrashToFile(crashInfo)
                
                // 2. 添加到队列等待上报
                crashQueue.offer(crashInfo)
                
                // 3. 尝试上报崩溃信息
                if (shouldReportCrash()) {
                    reportCrashes()
                }
                
                // 4. 清理旧的崩溃文件
                cleanupOldCrashFiles()
                
                Log.i(TAG, "崩溃已记录: ${crashInfo.throwable::class.simpleName}")
            } catch (e: Exception) {
                Log.e(TAG, "记录崩溃失败", e)
            }
        }
    }
    
    /**
     * 记录恢复信息
     */
    fun recordRecovery(throwable: Throwable) {
        scope.launch {
            try {
                val recoveryInfo = RecoveryInfo(
                    timestamp = System.currentTimeMillis(),
                    throwableClass = throwable::class.simpleName ?: "Unknown",
                    throwableMessage = throwable.message ?: "No message",
                    recoverySuccessful = true
                )
                
                saveRecoveryToFile(recoveryInfo)
                Log.i(TAG, "恢复已记录: ${recoveryInfo.throwableClass}")
            } catch (e: Exception) {
                Log.e(TAG, "记录恢复失败", e)
            }
        }
    }
    
    /**
     * 获取崩溃统计
     */
    fun getCrashStats(): CrashStats {
        val crashDir = getCrashDirectory()
        val recoveryDir = getRecoveryDirectory()
        
        val crashFiles = crashDir?.listFiles()?.filter { it.isFile && it.name.endsWith(".json") } ?: emptyList()
        val recoveryFiles = recoveryDir?.listFiles()?.filter { it.isFile && it.name.endsWith(".json") } ?: emptyList()
        
        val today = SimpleDateFormat("yyyyMMdd", Locale.getDefault()).format(Date())
        val todayCrashes = crashFiles.count { it.name.startsWith("crash_$today") }
        val todayRecoveries = recoveryFiles.count { it.name.startsWith("recovery_$today") }
        
        return CrashStats(
            totalCrashes = crashFiles.size,
            totalRecoveries = recoveryFiles.size,
            todayCrashes = todayCrashes,
            todayRecoveries = todayRecoveries,
            lastCrashTime = getLastCrashTime(),
            lastRecoveryTime = getLastRecoveryTime(),
            crashRate = calculateCrashRate()
        )
    }
    
    /**
     * 手动上报所有崩溃信息
     */
    fun reportAllCrashes() {
        scope.launch {
            reportCrashes(force = true)
        }
    }
    
    /**
     * 清理所有崩溃文件
     */
    fun cleanupAllCrashFiles() {
        scope.launch {
            try {
                val crashDir = getCrashDirectory()
                val recoveryDir = getRecoveryDirectory()
                
                crashDir?.listFiles()?.forEach { it.delete() }
                recoveryDir?.listFiles()?.forEach { it.delete() }
                
                crashQueue.clear()
                
                Log.i(TAG, "所有崩溃文件已清理")
            } catch (e: Exception) {
                Log.e(TAG, "清理崩溃文件失败", e)
            }
        }
    }
    
    /**
     * 导出崩溃报告
     */
    suspend fun exportCrashReport(): String {
        return try {
            val crashDir = getCrashDirectory()
            val crashFiles = crashDir?.listFiles()
                ?.filter { it.isFile && it.name.endsWith(".json") }
                ?.sortedByDescending { it.lastModified() }
                ?.take(100) // 最多100个文件
            
            val crashes = crashFiles?.mapNotNull { file ->
                runCatching {
                    val jsonString = file.readText()
                    json.decodeFromString<GlobalExceptionHandler.CrashInfo>(jsonString)
                }.getOrNull()
            } ?: emptyList()
            
            val report = CrashReport(
                generatedAt = System.currentTimeMillis(),
                deviceInfo = collectDeviceInfo(),
                appInfo = collectAppInfo(),
                crashStats = getCrashStats(),
                recentCrashes = crashes.take(20) // 最近20个崩溃
            )
            
            json.encodeToString(report)
        } catch (e: Exception) {
            Log.e(TAG, "导出崩溃报告失败", e)
            "{\"error\": \"导出失败: ${e.message}\"}"
        }
    }
    
    private fun saveCrashToFile(crashInfo: GlobalExceptionHandler.CrashInfo) {
        try {
            val crashDir = getCrashDirectory() ?: return
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.getDefault()).format(Date(crashInfo.timestamp))
            val fileName = "crash_${timestamp}_${crashInfo.throwable::class.simpleName ?: "Unknown"}.json"
            val file = File(crashDir, fileName)
            
            val jsonString = json.encodeToString(crashInfo)
            file.writeText(jsonString)
            
            // 更新最后崩溃时间
            updateLastCrashTime(crashInfo.timestamp)
            
            Log.d(TAG, "崩溃已保存到文件: ${file.absolutePath}")
        } catch (e: Exception) {
            Log.e(TAG, "保存崩溃文件失败", e)
        }
    }
    
    private fun saveRecoveryToFile(recoveryInfo: RecoveryInfo) {
        try {
            val recoveryDir = getRecoveryDirectory() ?: return
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.getDefault()).format(Date(recoveryInfo.timestamp))
            val fileName = "recovery_${timestamp}.json"
            val file = File(recoveryDir, fileName)
            
            val jsonString = json.encodeToString(recoveryInfo)
            file.writeText(jsonString)
            
            // 更新最后恢复时间
            updateLastRecoveryTime(recoveryInfo.timestamp)
            
            Log.d(TAG, "恢复已保存到文件: ${file.absolutePath}")
        } catch (e: Exception) {
            Log.e(TAG, "保存恢复文件失败", e)
        }
    }
    
    private fun reportCrashes(force: Boolean = false) {
        if (!force && !shouldReportCrash()) {
            return
        }
        
        if (isReporting.getAndIncrement() > 0) {
            // 已经在上报中
            isReporting.decrementAndGet()
            return
        }
        
        scope.launch {
            try {
                val crashesToReport = mutableListOf<GlobalExceptionHandler.CrashInfo>()
                while (crashQueue.isNotEmpty()) {
                    crashesToReport.add(crashQueue.poll())
                }
                
                if (crashesToReport.isNotEmpty()) {
                    // 在实际项目中，这里应该将崩溃信息上报到服务器
                    // 这里简化实现，只记录到日志
                    Log.i(TAG, "准备上报 ${crashesToReport.size} 个崩溃信息")
                    
                    // 模拟上报
                    val success = simulateCrashReport(crashesToReport)
                    
                    if (success) {
                        Log.i(TAG, "崩溃信息上报成功")
                        // 上报成功后清理本地文件
                        cleanupReportedCrashes(crashesToReport)
                    } else {
                        Log.w(TAG, "崩溃信息上报失败，重新加入队列")
                        // 上报失败，重新加入队列
                        crashesToReport.forEach { crashQueue.offer(it) }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "上报崩溃信息失败", e)
            } finally {
                isReporting.decrementAndGet()
            }
        }
    }
    
    private fun simulateCrashReport(crashes: List<GlobalExceptionHandler.CrashInfo>): Boolean {
        // 模拟网络请求
        return try {
            // 在实际项目中，这里应该发送HTTP请求到服务器
            // 这里简化实现，随机返回成功或失败
            Thread.sleep(100) // 模拟网络延迟
            Math.random() > 0.1 // 90%的成功率
        } catch (e: Exception) {
            false
        }
    }
    
    private fun cleanupReportedCrashes(crashes: List<GlobalExceptionHandler.CrashInfo>) {
        try {
            val crashDir = getCrashDirectory() ?: return
            
            crashes.forEach { crashInfo ->
                val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.getDefault()).format(Date(crashInfo.timestamp))
                val fileName = "crash_${timestamp}_${crashInfo.throwable::class.simpleName ?: "Unknown"}.json"
                val file = File(crashDir, fileName)
                
                if (file.exists()) {
                    file.delete()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "清理已上报崩溃文件失败", e)
        }
    }
    
    private fun cleanupOldCrashFiles() {
        try {
            val crashDir = getCrashDirectory() ?: return
            val recoveryDir = getRecoveryDirectory() ?: return
            
            // 清理旧的崩溃文件
            cleanupOldFilesInDirectory(crashDir, maxCrashFiles, maxCrashSize)
            
            // 清理旧的恢复文件
            cleanupOldFilesInDirectory(recoveryDir, maxCrashFiles / 2, maxCrashSize / 2)
        } catch (e: Exception) {
            Log.e(TAG, "清理旧崩溃文件失败", e)
        }
    }
    
    private fun cleanupOldFilesInDirectory(directory: File, maxFiles: Int, maxSize: Long) {
        val files = directory.listFiles()?.filter { it.isFile && it.name.endsWith(".json") } ?: return
        
        // 按修改时间排序（旧的文件在前）
        val sortedFiles = files.sortedBy { it.lastModified() }
        
        // 检查文件数量
        if (sortedFiles.size > maxFiles) {
            val filesToDelete = sortedFiles.take(sortedFiles.size - maxFiles)
            filesToDelete.forEach { it.delete() }
            Log.d(TAG, "删除了 ${filesToDelete.size} 个旧文件（超过最大数量限制）")
        }
        
        // 检查文件总大小
        val remainingFiles = directory.listFiles()?.filter { it.isFile && it.name.endsWith(".json") } ?: return
        var totalSize = remainingFiles.sumOf { it.length() }
        
        if (totalSize > maxSize) {
            // 按修改时间排序（旧的文件在前）
            val sizeSortedFiles = remainingFiles.sortedBy { it.lastModified() }
            
            for (file in sizeSortedFiles) {
                if (totalSize <= maxSize) break
                
                val fileSize = file.length()
                if (file.delete()) {
                    totalSize -= fileSize
                    Log.d(TAG, "删除了文件 ${file.name}（超过最大大小限制）")
                }
            }
        }
    }
    
    private fun shouldReportCrash(): Boolean {
        // 检查网络连接
        // 检查是否在WiFi环境下
        // 检查是否在充电状态
        // 检查是否在用户活跃时间段
        // 这里简化实现，随机决定是否上报
        return Math.random() > 0.3 // 70%的概率上报
    }
    
    private fun getCrashDirectory(): File? {
        return try {
            val dir = File(context.filesDir, "crashes")
            if (!dir.exists()) {
                dir.mkdirs()
            }
            dir
        } catch (e: Exception) {
            Log.e(TAG, "获取崩溃目录失败", e)
            null
        }
    }
    
    private fun getRecoveryDirectory(): File? {
        return try {
            val dir = File(context.filesDir, "recoveries")
            if (!dir.exists()) {
                dir.mkdirs()
            }
            dir
        } catch (e: Exception) {
            Log.e(TAG, "获取恢复目录失败", e)
            null
        }
    }
    
    private fun updateLastCrashTime(timestamp: Long) {
        val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
        prefs.edit().putLong("last_crash_time", timestamp).apply()
    }
    
    private fun updateLastRecoveryTime(timestamp: Long) {
        val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
        prefs.edit().putLong("last_recovery_time", timestamp).apply()
    }
    
    private fun getLastCrashTime(): Long {
        val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
        return prefs.getLong("last_crash_time", 0)
    }
    
    private fun getLastRecoveryTime(): Long {
        val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
        return prefs.getLong("last_recovery_time", 0)
    }
    
    private fun calculateCrashRate(): Double {
        val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
        val crashCount = prefs.getInt("crash_count_30d", 0)
        val sessionCount = prefs.getInt("session_count_30d", 1) // 避免除零
        
        return crashCount.toDouble() / sessionCount.toDouble()
    }
    
    private fun collectDeviceInfo(): GlobalExceptionHandler.DeviceInfo {
        return GlobalExceptionHandler.DeviceInfo(
            manufacturer = Build.MANUFACTURER,
            model = Build.MODEL,
            brand = Build.BRAND,
            device = Build.DEVICE,
            product = Build.PRODUCT,
            sdkVersion = Build.VERSION.SDK_INT,
            releaseVersion = Build.VERSION.RELEASE,
            fingerprint = Build.FINGERPRINT
        )
    }
    
    private fun collectAppInfo(): AppInfo {
        return try {
            val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
            val appName = context.applicationInfo.loadLabel(context.packageManager).toString()
            
            AppInfo(
                packageName = context.packageName,
                appName = appName,
                versionName = packageInfo.versionName ?: "unknown",
                versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    packageInfo.longVersionCode
                } else {
                    @Suppress("DEPRECATION")
                    packageInfo.versionCode.toLong()
                },
                installTime = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    packageInfo.firstInstallTime
                } else {
                    0L
                },
                lastUpdateTime = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    packageInfo.lastUpdateTime
                } else {
                    0L
                }
            )
        } catch (e: Exception) {
            AppInfo()
        }
    }
    
    /**
     * 恢复信息
     */
    data class RecoveryInfo(
        val timestamp: Long,
        val throwableClass: String,
        val throwableMessage: String,
        val recoverySuccessful: Boolean,
        val recoveryTimeMs: Long = System.currentTimeMillis() - timestamp
    )
    
    /**
     * 崩溃统计
     */
    data class CrashStats(
        val totalCrashes: Int = 0,
        val totalRecoveries: Int = 0,
        val todayCrashes: Int = 0,
        val todayRecoveries: Int = 0,
        val lastCrashTime: Long = 0,
        val lastRecoveryTime: Long = 0,
        val crashRate: Double = 0.0
    ) {
        val formattedLastCrashTime: String
            get() = if (lastCrashTime > 0) {
                SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(lastCrashTime))
            } else {
                "从未"
            }
        
        val formattedLastRecoveryTime: String
            get() = if (lastRecoveryTime > 0) {
                SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(lastRecoveryTime))
            } else {
                "从未"
            }
        
        val crashRatePercentage: String
            get() = String.format("%.2f%%", crashRate * 100)
    }
    
    /**
     * 应用信息
     */
    data class AppInfo(
        val packageName: String = "unknown",
        val appName: String = "unknown",
        val versionName: String = "unknown",
        val versionCode: Long = 0,
        val installTime: Long = 0,
        val lastUpdateTime: Long = 0
    ) {
        val formattedInstallTime: String
            get() = if (installTime > 0) {
                SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(installTime))
            } else {
                "未知"
            }
        
        val formattedLastUpdateTime: String
            get() = if (lastUpdateTime > 0) {
                SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(lastUpdateTime))
            } else {
                "未知"
            }
    }
    
    /**
     * 崩溃报告
     */
    data class CrashReport(
        val generatedAt: Long,
        val deviceInfo: GlobalExceptionHandler.DeviceInfo,
        val appInfo: AppInfo,
        val crashStats: CrashStats,
        val recentCrashes: List<GlobalExceptionHandler.CrashInfo>
    ) {
        val formattedGeneratedAt: String
            get() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(generatedAt))
    }
    
    companion object {
        private const val TAG = "CrashReporter"
        
        /**
         * 记录会话开始（用于计算崩溃率）
         */
        @JvmStatic
        fun recordSessionStart(context: Context) {
            val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
            val today = SimpleDateFormat("yyyyMMdd", Locale.getDefault()).format(Date())
            val key = "session_$today"
            
            val sessionCount = prefs.getInt(key, 0)
            prefs.edit().putInt(key, sessionCount + 1).apply()
            
            // 更新30天会话计数
            val sessionCount30d = prefs.getInt("session_count_30d", 0)
            prefs.edit().putInt("session_count_30d", sessionCount30d + 1).apply()
        }
        
        /**
         * 记录会话结束
         */
        @JvmStatic
        fun recordSessionEnd(context: Context, success: Boolean) {
            val prefs = context.getSharedPreferences("crash_stats", Context.MODE_PRIVATE)
            val today = SimpleDateFormat("yyyyMMdd", Locale.getDefault()).format(Date())
            val key = "session_success_$today"
            
            val successCount = prefs.getInt(key, 0)
            if (success) {
                prefs.edit().putInt(key, successCount + 1).apply()
            }
        }
    }
}