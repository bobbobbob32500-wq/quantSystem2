package com.quant.system.core.performance

import android.app.Activity
import android.content.Context
import androidx.fragment.app.Fragment
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.lang.ref.WeakReference
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.max

/**
 * 内存泄漏检测器
 * 检测Activity、Fragment、ViewModel等组件的内存泄漏
 */
class MemoryLeakDetector(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val trackedObjects = ConcurrentHashMap<String, TrackedObject>()
    private val leakListeners = mutableListOf<LeakListener>()
    
    private var monitoringJob: Job? = null
    private var isEnabled = false
    
    /**
     * 开始内存泄漏检测
     */
    fun startMonitoring(checkIntervalMs: Long = 30000L) {
        if (isEnabled) return
        
        isEnabled = true
        monitoringJob = scope.launch {
            while (isEnabled) {
                checkForLeaks()
                delay(checkIntervalMs)
            }
        }
    }
    
    /**
     * 停止内存泄漏检测
     */
    fun stopMonitoring() {
        isEnabled = false
        monitoringJob?.cancel()
        monitoringJob = null
    }
    
    /**
     * 跟踪Activity
     */
    fun trackActivity(activity: Activity) {
        val key = "Activity:${activity.javaClass.simpleName}@${System.identityHashCode(activity)}"
        trackObject(key, activity, LeakType.ACTIVITY)
        
        // 监听Activity生命周期
        activity.lifecycle.addObserver(object : LifecycleEventObserver {
            override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
                when (event) {
                    Lifecycle.Event.ON_DESTROY -> {
                        // Activity销毁，标记为待检查
                        trackedObjects[key]?.let { obj ->
                            obj.destroyedAt = System.currentTimeMillis()
                            obj.isDestroyed = true
                        }
                    }
                    else -> Unit
                }
            }
        })
    }
    
    /**
     * 跟踪Fragment
     */
    fun trackFragment(fragment: Fragment) {
        val key = "Fragment:${fragment.javaClass.simpleName}@${System.identityHashCode(fragment)}"
        trackObject(key, fragment, LeakType.FRAGMENT)
        
        // 监听Fragment生命周期
        fragment.lifecycle.addObserver(object : LifecycleEventObserver {
            override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
                when (event) {
                    Lifecycle.Event.ON_DESTROY -> {
                        // Fragment销毁，标记为待检查
                        trackedObjects[key]?.let { obj ->
                            obj.destroyedAt = System.currentTimeMillis()
                            obj.isDestroyed = true
                        }
                    }
                    else -> Unit
                }
            }
        })
    }
    
    /**
     * 跟踪ViewModel
     */
    fun trackViewModel(viewModel: Any) {
        val key = "ViewModel:${viewModel.javaClass.simpleName}@${System.identityHashCode(viewModel)}"
        trackObject(key, viewModel, LeakType.VIEW_MODEL)
    }
    
    /**
     * 跟踪资源（如Bitmap、数据库连接等）
     */
    fun trackResource(resource: Any, type: String) {
        val key = "Resource:$type@${System.identityHashCode(resource)}"
        trackObject(key, resource, LeakType.RESOURCE)
    }
    
    /**
     * 添加泄漏监听器
     */
    fun addLeakListener(listener: LeakListener) {
        leakListeners.add(listener)
    }
    
    /**
     * 移除泄漏监听器
     */
    fun removeLeakListener(listener: LeakListener) {
        leakListeners.remove(listener)
    }
    
    /**
     * 获取泄漏统计
     */
    fun getLeakStats(): LeakStats {
        val now = System.currentTimeMillis()
        val allObjects = trackedObjects.values.toList()
        val leakedObjects = allObjects.filter { it.isDestroyed && !it.isCollected && now - it.destroyedAt > LEAK_DETECTION_DELAY_MS }
        
        return LeakStats(
            totalTracked = allObjects.size,
            destroyedCount = allObjects.count { it.isDestroyed },
            leakedCount = leakedObjects.size,
            leaksByType = leakedObjects.groupBy { it.type }.mapValues { it.value.size },
            recentLeaks = leakedObjects.take(10).map { it.toLeakInfo() }
        )
    }
    
    /**
     * 强制垃圾回收并检查泄漏
     */
    fun forceGcAndCheck(): LeakStats {
        Runtime.getRuntime().gc()
        System.runFinalization()
        Thread.sleep(100) // 给GC一点时间
        
        checkForLeaks()
        return getLeakStats()
    }
    
    /**
     * 清理已回收的对象
     */
    fun cleanupCollectedObjects() {
        val iterator = trackedObjects.iterator()
        while (iterator.hasNext()) {
            val (key, obj) = iterator.next()
            if (obj.isCollected) {
                iterator.remove()
            }
        }
    }
    
    private fun trackObject(key: String, obj: Any, type: LeakType) {
        val weakRef = WeakReference(obj)
        val trackedObj = TrackedObject(
            key = key,
            weakRef = weakRef,
            type = type,
            createdAt = System.currentTimeMillis(),
            stackTrace = Thread.currentThread().stackTrace.copyOfRange(2, minOf(12, Thread.currentThread().stackTrace.size))
        )
        
        trackedObjects[key] = trackedObj
    }
    
    private fun checkForLeaks() {
        val now = System.currentTimeMillis()
        val leakedObjects = mutableListOf<TrackedObject>()
        
        trackedObjects.values.forEach { obj ->
            // 检查对象是否已被回收
            if (obj.weakRef.get() == null) {
                obj.isCollected = true
                obj.collectedAt = now
            }
            
            // 检查泄漏：对象已销毁但未被回收
            if (obj.isDestroyed && !obj.isCollected && now - obj.destroyedAt > LEAK_DETECTION_DELAY_MS) {
                leakedObjects.add(obj)
            }
        }
        
        // 通知泄漏监听器
        if (leakedObjects.isNotEmpty()) {
            val leakInfos = leakedObjects.map { it.toLeakInfo() }
            leakListeners.forEach { listener ->
                try {
                    listener.onLeaksDetected(leakInfos)
                } catch (e: Exception) {
                    // 忽略监听器异常
                }
            }
            
            // 记录到日志
            leakedObjects.forEach { obj ->
                android.util.Log.w(
                    "MemoryLeakDetector",
                    "检测到内存泄漏: ${obj.key}\n" +
                            "类型: ${obj.type}\n" +
                            "创建时间: ${obj.createdAt}\n" +
                            "销毁时间: ${obj.destroyedAt}\n" +
                            "创建堆栈:\n${obj.stackTrace.joinToString("\n")}"
                )
            }
        }
        
        // 清理已回收的对象
        cleanupCollectedObjects()
    }
    
    /**
     * 跟踪的对象
     */
    private data class TrackedObject(
        val key: String,
        val weakRef: WeakReference<Any>,
        val type: LeakType,
        val createdAt: Long,
        val stackTrace: Array<StackTraceElement>,
        var isDestroyed: Boolean = false,
        var destroyedAt: Long = 0,
        var isCollected: Boolean = false,
        var collectedAt: Long = 0
    ) {
        fun toLeakInfo(): LeakInfo {
            return LeakInfo(
                key = key,
                type = type,
                createdAt = createdAt,
                destroyedAt = destroyedAt,
                ageMs = if (isDestroyed) destroyedAt - createdAt else System.currentTimeMillis() - createdAt,
                stackTrace = stackTrace.copyOf()
            )
        }
        
        override fun equals(other: Any?): Boolean {
            if (this === other) return true
            if (javaClass != other?.javaClass) return false
            
            other as TrackedObject
            
            if (key != other.key) return false
            if (type != other.type) return false
            if (createdAt != other.createdAt) return false
            if (isDestroyed != other.isDestroyed) return false
            if (destroyedAt != other.destroyedAt) return false
            if (isCollected != other.isCollected) return false
            if (collectedAt != other.collectedAt) return false
            
            return true
        }
        
        override fun hashCode(): Int {
            var result = key.hashCode()
            result = 31 * result + type.hashCode()
            result = 31 * result + createdAt.hashCode()
            result = 31 * result + isDestroyed.hashCode()
            result = 31 * result + destroyedAt.hashCode()
            result = 31 * result + isCollected.hashCode()
            result = 31 * result + collectedAt.hashCode()
            return result
        }
    }
    
    /**
     * 泄漏类型
     */
    enum class LeakType {
        ACTIVITY,
        FRAGMENT,
        VIEW_MODEL,
        RESOURCE,
        OTHER
    }
    
    /**
     * 泄漏信息
     */
    data class LeakInfo(
        val key: String,
        val type: LeakType,
        val createdAt: Long,
        val destroyedAt: Long,
        val ageMs: Long,
        val stackTrace: Array<StackTraceElement>
    ) {
        override fun equals(other: Any?): Boolean {
            if (this === other) return true
            if (javaClass != other?.javaClass) return false
            
            other as LeakInfo
            
            if (key != other.key) return false
            if (type != other.type) return false
            if (createdAt != other.createdAt) return false
            if (destroyedAt != other.destroyedAt) return false
            if (ageMs != other.ageMs) return false
            if (!stackTrace.contentEquals(other.stackTrace)) return false
            
            return true
        }
        
        override fun hashCode(): Int {
            var result = key.hashCode()
            result = 31 * result + type.hashCode()
            result = 31 * result + createdAt.hashCode()
            result = 31 * result + destroyedAt.hashCode()
            result = 31 * result + ageMs.hashCode()
            result = 31 * result + stackTrace.contentHashCode()
            return result
        }
    }
    
    /**
     * 泄漏统计
     */
    data class LeakStats(
        val totalTracked: Int,
        val destroyedCount: Int,
        val leakedCount: Int,
        val leaksByType: Map<LeakType, Int>,
        val recentLeaks: List<LeakInfo>
    ) {
        val leakPercentage: Double
            get() = if (destroyedCount > 0) leakedCount.toDouble() / destroyedCount.toDouble() * 100 else 0.0
        
        val hasLeaks: Boolean
            get() = leakedCount > 0
    }
    
    /**
     * 泄漏监听器接口
     */
    interface LeakListener {
        fun onLeaksDetected(leaks: List<LeakInfo>)
    }
    
    companion object {
        private const val LEAK_DETECTION_DELAY_MS = 5000L // 5秒后检查泄漏
        
        private val instanceMap = ConcurrentHashMap<Context, MemoryLeakDetector>()
        
        @JvmStatic
        fun getInstance(context: Context): MemoryLeakDetector {
            return instanceMap.getOrPut(context) {
                MemoryLeakDetector(context.applicationContext ?: context)
            }
        }
        
        /**
         * 快速检查Activity泄漏
         */
        @JvmStatic
        fun checkActivityLeak(activity: Activity): Boolean {
            val detector = getInstance(activity)
            detector.trackActivity(activity)
            
            // 简单检查：如果Activity已经onDestroy但未被回收，可能泄漏
            return detector.getLeakStats().hasLeaks
        }
        
        /**
         * 获取全局泄漏统计
         */
        @JvmStatic
        fun getGlobalLeakStats(): Map<Context, LeakStats> {
            return instanceMap.mapValues { it.value.getLeakStats() }
        }
        
        /**
         * 清理所有检测器
         */
        @JvmStatic
        fun cleanupAll() {
            instanceMap.values.forEach { it.stopMonitoring() }
            instanceMap.clear()
        }
    }
}