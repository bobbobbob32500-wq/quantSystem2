package com.quant.system.core.stability

import android.app.Application
import android.content.Context
import android.os.Build
import android.os.Looper
import android.util.Log
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 全局异常处理器
 * 捕获未处理的异常，防止应用崩溃
 */
class GlobalExceptionHandler private constructor(private val context: Context) : Thread.UncaughtExceptionHandler {
    
    private val originalHandler = Thread.getDefaultUncaughtExceptionHandler()
    private val isHandling = AtomicBoolean(false)
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val crashReporter = CrashReporter(context)
    
    init {
        Thread.setDefaultUncaughtExceptionHandler(this)
    }
    
    override fun uncaughtException(thread: Thread, throwable: Throwable) {
        if (isHandling.getAndSet(true)) {
            // 已经在处理异常，交给原始处理器
            originalHandler?.uncaughtException(thread, throwable)
            return
        }
        
        try {
            // 记录崩溃信息
            val crashInfo = collectCrashInfo(thread, throwable)
            crashReporter.recordCrash(crashInfo)
            
            // 尝试恢复应用
            if (shouldAttemptRecovery(throwable)) {
                attemptRecovery(thread, throwable)
            } else {
                // 无法恢复，交给原始处理器
                originalHandler?.uncaughtException(thread, throwable)
            }
        } catch (e: Exception) {
            // 异常处理过程中发生错误，交给原始处理器
            originalHandler?.uncaughtException(thread, throwable)
        } finally {
            isHandling.set(false)
        }
    }
    
    /**
     * 获取协程异常处理器
     */
    fun getCoroutineExceptionHandler(): CoroutineExceptionHandler {
        return CoroutineExceptionHandler { _, throwable ->
            handleCoroutineException(throwable)
        }
    }
    
    /**
     * 处理协程异常
     */
    private fun handleCoroutineException(throwable: Throwable) {
        scope.launch {
            try {
                val crashInfo = CrashInfo(
                    timestamp = System.currentTimeMillis(),
                    threadName = "Coroutine",
                    throwable = throwable,
                    isCoroutine = true,
                    appState = collectAppState()
                )
                crashReporter.recordCrash(crashInfo)
                
                // 根据异常类型决定是否恢复
                if (isRecoverableCoroutineException(throwable)) {
                    Log.w(TAG, "协程异常已处理: ${throwable.message}")
                } else {
                    // 严重异常，需要重启应用
                    restartApplication()
                }
            } catch (e: Exception) {
                Log.e(TAG, "处理协程异常时出错", e)
            }
        }
    }
    
    /**
     * 收集崩溃信息
     */
    private fun collectCrashInfo(thread: Thread, throwable: Throwable): CrashInfo {
        return CrashInfo(
            timestamp = System.currentTimeMillis(),
            threadName = thread.name,
            throwable = throwable,
            isCoroutine = false,
            appState = collectAppState(),
            deviceInfo = collectDeviceInfo(),
            userInfo = collectUserInfo()
        )
    }
    
    /**
     * 收集应用状态
     */
    private fun collectAppState(): AppState {
        return try {
            val memoryInfo = Runtime.getRuntime()
            AppState(
                memoryUsage = MemoryUsage(
                    totalMemory = memoryInfo.totalMemory(),
                    freeMemory = memoryInfo.freeMemory(),
                    maxMemory = memoryInfo.maxMemory(),
                    usedMemory = memoryInfo.totalMemory() - memoryInfo.freeMemory()
                ),
                threadCount = Thread.activeCount(),
                isMainThread = Looper.getMainLooper().thread == Thread.currentThread(),
                uptime = System.currentTimeMillis() - appStartTime
            )
        } catch (e: Exception) {
            AppState()
        }
    }
    
    /**
     * 收集设备信息
     */
    private fun collectDeviceInfo(): DeviceInfo {
        return DeviceInfo(
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
    
    /**
     * 收集用户信息（匿名化）
     */
    private fun collectUserInfo(): UserInfo {
        return try {
            val prefs = context.getSharedPreferences("user_prefs", Context.MODE_PRIVATE)
            UserInfo(
                userId = prefs.getString("user_id", null)?.hashCode()?.toString() ?: "anonymous",
                appVersion = context.packageManager.getPackageInfo(context.packageName, 0).versionName,
                installTime = getInstallTime(),
                lastCrashTime = prefs.getLong("last_crash_time", 0)
            )
        } catch (e: Exception) {
            UserInfo()
        }
    }
    
    /**
     * 判断是否应该尝试恢复
     */
    private fun shouldAttemptRecovery(throwable: Throwable): Boolean {
        // 以下异常类型可以尝试恢复
        return when {
            throwable is OutOfMemoryError -> false // 内存不足，无法恢复
            throwable is StackOverflowError -> false // 栈溢出，无法恢复
            throwable is NoClassDefFoundError -> false // 类定义未找到，无法恢复
            throwable is IllegalStateException -> true // 状态异常，可以尝试恢复
            throwable is IllegalArgumentException -> true // 参数异常，可以尝试恢复
            throwable is NullPointerException -> true // 空指针，可以尝试恢复
            throwable is SecurityException -> false // 安全异常，无法恢复
            else -> true // 其他异常尝试恢复
        }
    }
    
    /**
     * 判断是否为可恢复的协程异常
     */
    private fun isRecoverableCoroutineException(throwable: Throwable): Boolean {
        return when {
            throwable is kotlinx.coroutines.CancellationException -> true // 协程取消，可恢复
            throwable is java.util.concurrent.CancellationException -> true // 任务取消，可恢复
            throwable is java.net.SocketTimeoutException -> true // 网络超时，可恢复
            throwable is java.io.IOException -> true // IO异常，可恢复
            else -> false
        }
    }
    
    /**
     * 尝试恢复应用
     */
    private fun attemptRecovery(thread: Thread, throwable: Throwable) {
        Log.e(TAG, "尝试恢复应用", throwable)
        
        try {
            // 1. 清理资源
            cleanupResources()
            
            // 2. 重启主线程
            if (thread == Looper.getMainLooper().thread) {
                restartMainThread()
            }
            
            // 3. 记录恢复日志
            crashReporter.recordRecovery(throwable)
            
            // 4. 通知用户
            showRecoveryNotification()
            
        } catch (e: Exception) {
            Log.e(TAG, "恢复应用失败", e)
            // 恢复失败，交给原始处理器
            originalHandler?.uncaughtException(thread, throwable)
        }
    }
    
    /**
     * 清理资源
     */
    private fun cleanupResources() {
        // 清理图片缓存
        try {
            val cacheDir = context.cacheDir
            cacheDir?.listFiles()?.forEach { file ->
                if (file.isFile && file.name.startsWith("image_cache_")) {
                    file.delete()
                }
            }
        } catch (e: Exception) {
            // 忽略清理错误
        }
        
        // 清理临时文件
        try {
            val tempDir = File(context.cacheDir, "temp")
            if (tempDir.exists() && tempDir.isDirectory) {
                tempDir.listFiles()?.forEach { file ->
                    if (file.isFile && file.lastModified() < System.currentTimeMillis() - 3600000) { // 1小时前
                        file.delete()
                    }
                }
            }
        } catch (e: Exception) {
            // 忽略清理错误
        }
        
        // 清理内存
        Runtime.getRuntime().gc()
        System.runFinalization()
    }
    
    /**
     * 重启主线程
     */
    private fun restartMainThread() {
        // 在实际项目中，这里应该重启Activity或应用
        // 这里简化实现，只记录日志
        Log.i(TAG, "主线程已重启")
    }
    
    /**
     * 重启应用
     */
    private fun restartApplication() {
        // 在实际项目中，这里应该重启应用
        // 这里简化实现，只记录日志
        Log.i(TAG, "应用需要重启")
        
        // 保存重启标记
        val prefs = context.getSharedPreferences("crash_recovery", Context.MODE_PRIVATE)
        prefs.edit().putLong("last_restart_time", System.currentTimeMillis()).apply()
    }
    
    /**
     * 显示恢复通知
     */
    private fun showRecoveryNotification() {
        // 在实际项目中，这里应该显示一个Toast或Snackbar通知用户
        Log.i(TAG, "应用已从异常中恢复")
    }
    
    /**
     * 获取应用安装时间
     */
    private fun getInstallTime(): Long {
        return try {
            val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                packageInfo.firstInstallTime
            } else {
                File(context.packageCodePath).lastModified()
            }
        } catch (e: Exception) {
            0L
        }
    }
    
    companion object {
        private const val TAG = "GlobalExceptionHandler"
        private var appStartTime = System.currentTimeMillis()
        
        private val instanceMap = mutableMapOf<Context, GlobalExceptionHandler>()
        
        @JvmStatic
        fun init(application: Application): GlobalExceptionHandler {
            return instanceMap.getOrPut(application) {
                GlobalExceptionHandler(application)
            }
        }
        
        @JvmStatic
        fun getInstance(context: Context): GlobalExceptionHandler {
            return instanceMap[context] ?: throw IllegalStateException("GlobalExceptionHandler not initialized")
        }
        
        /**
         * 记录应用启动时间
         */
        @JvmStatic
        fun recordAppStart() {
            appStartTime = System.currentTimeMillis()
        }
        
        /**
         * 记录关键操作
         */
        @JvmStatic
        fun logCriticalOperation(operation: String, success: Boolean, durationMs: Long = 0) {
            Log.i(TAG, "关键操作: $operation, 成功: $success, 耗时: ${durationMs}ms")
        }
    }
    
    /**
     * 崩溃信息
     */
    data class CrashInfo(
        val timestamp: Long,
        val threadName: String,
        val throwable: Throwable,
        val isCoroutine: Boolean,
        val appState: AppState = AppState(),
        val deviceInfo: DeviceInfo = DeviceInfo(),
        val userInfo: UserInfo = UserInfo()
    ) {
        val stackTrace: String
            get() {
                val sw = StringWriter()
                val pw = PrintWriter(sw)
                throwable.printStackTrace(pw)
                return sw.toString()
            }
        
        val formattedTime: String
            get() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(timestamp))
    }
    
    /**
     * 应用状态
     */
    data class AppState(
        val memoryUsage: MemoryUsage = MemoryUsage(),
        val threadCount: Int = 0,
        val isMainThread: Boolean = false,
        val uptime: Long = 0
    )
    
    /**
     * 内存使用情况
     */
    data class MemoryUsage(
        val totalMemory: Long = 0,
        val freeMemory: Long = 0,
        val maxMemory: Long = 0,
        val usedMemory: Long = 0
    ) {
        val usagePercentage: Int
            get() = if (totalMemory > 0) ((usedMemory.toDouble() / totalMemory.toDouble()) * 100).toInt() else 0
    }
    
    /**
     * 设备信息
     */
    data class DeviceInfo(
        val manufacturer: String = "unknown",
        val model: String = "unknown",
        val brand: String = "unknown",
        val device: String = "unknown",
        val product: String = "unknown",
        val sdkVersion: Int = 0,
        val releaseVersion: String = "unknown",
        val fingerprint: String = "unknown"
    )
    
    /**
     * 用户信息（匿名化）
     */
    data class UserInfo(
        val userId: String = "anonymous",
        val appVersion: String = "unknown",
        val installTime: Long = 0,
        val lastCrashTime: Long = 0
    )
}