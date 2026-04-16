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
 * 鍐呭瓨娉勬紡妫€娴嬪櫒
 * 妫€娴婣ctivity銆丗ragment銆乂iewModel绛夌粍浠剁殑鍐呭瓨娉勬紡
 */
class MemoryLeakDetector(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val trackedObjects = ConcurrentHashMap<String, TrackedObject>()
    private val leakListeners = mutableListOf<LeakListener>()
    
    private var monitoringJob: Job? = null
    private var isEnabled = false
    
    /**
     * 寮€濮嬪唴瀛樻硠婕忔娴?
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
     * 鍋滄鍐呭瓨娉勬紡妫€娴?
     */
    fun stopMonitoring() {
        isEnabled = false
        monitoringJob?.cancel()
        monitoringJob = null
    }
    
    /**
     * 璺熻釜Activity
     */
    fun trackActivity(activity: Activity) {
        val key = "Activity:${activity.javaClass.simpleName}@${System.identityHashCode(activity)}"
        trackObject(key, activity, LeakType.ACTIVITY)
        
        // 鐩戝惉Activity鐢熷懡鍛ㄦ湡
        if (activity is LifecycleOwner) {
            activity.lifecycle.addObserver(object : LifecycleEventObserver {
                override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
                    when (event) {
                        Lifecycle.Event.ON_DESTROY -> {
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
    }
    
    /**
     * 璺熻釜Fragment
     */
    fun trackFragment(fragment: Fragment) {
        val key = "Fragment:${fragment.javaClass.simpleName}@${System.identityHashCode(fragment)}"
        trackObject(key, fragment, LeakType.FRAGMENT)
        
        // 鐩戝惉Fragment鐢熷懡鍛ㄦ湡
        fragment.lifecycle.addObserver(object : LifecycleEventObserver {
            override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
                when (event) {
                    Lifecycle.Event.ON_DESTROY -> {
                        // Fragment閿€姣侊紝鏍囪涓哄緟妫€鏌?
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
     * 璺熻釜ViewModel
     */
    fun trackViewModel(viewModel: Any) {
        val key = "ViewModel:${viewModel.javaClass.simpleName}@${System.identityHashCode(viewModel)}"
        trackObject(key, viewModel, LeakType.VIEW_MODEL)
    }
    
    /**
     * 璺熻釜璧勬簮锛堝Bitmap銆佹暟鎹簱杩炴帴绛夛級
     */
    fun trackResource(resource: Any, type: String) {
        val key = "Resource:$type@${System.identityHashCode(resource)}"
        trackObject(key, resource, LeakType.RESOURCE)
    }
    
    /**
     * 娣诲姞娉勬紡鐩戝惉鍣?
     */
    fun addLeakListener(listener: LeakListener) {
        leakListeners.add(listener)
    }
    
    /**
     * 绉婚櫎娉勬紡鐩戝惉鍣?
     */
    fun removeLeakListener(listener: LeakListener) {
        leakListeners.remove(listener)
    }
    
    /**
     * 鑾峰彇娉勬紡缁熻
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
     * 寮哄埗鍨冨溇鍥炴敹骞舵鏌ユ硠婕?
     */
    fun forceGcAndCheck(): LeakStats {
        Runtime.getRuntime().gc()
        System.runFinalization()
        Thread.sleep(100) // 缁橤C涓€鐐规椂闂?
        
        checkForLeaks()
        return getLeakStats()
    }
    
    /**
     * 娓呯悊宸插洖鏀剁殑瀵硅薄
     */
    fun cleanupCollectedObjects() {
        val iterator = trackedObjects.iterator()
        while (iterator.hasNext()) {
            val (_, obj) = iterator.next()
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
            // 妫€鏌ュ璞℃槸鍚﹀凡琚洖鏀?
            if (obj.weakRef.get() == null) {
                obj.isCollected = true
                obj.collectedAt = now
            }
            
            // 妫€鏌ユ硠婕忥細瀵硅薄宸查攢姣佷絾鏈鍥炴敹
            if (obj.isDestroyed && !obj.isCollected && now - obj.destroyedAt > LEAK_DETECTION_DELAY_MS) {
                leakedObjects.add(obj)
            }
        }
        
        // 閫氱煡娉勬紡鐩戝惉鍣?
        if (leakedObjects.isNotEmpty()) {
            val leakInfos = leakedObjects.map { it.toLeakInfo() }
            leakListeners.forEach { listener ->
                try {
                    listener.onLeaksDetected(leakInfos)
                } catch (e: Exception) {
                    // 蹇界暐鐩戝惉鍣ㄥ紓甯?
                }
            }
            
            // 璁板綍鍒版棩蹇?
            leakedObjects.forEach { obj ->
                android.util.Log.w(
                    "MemoryLeakDetector",
                    "妫€娴嬪埌鍐呭瓨娉勬紡: ${obj.key}\n" +
                            "绫诲瀷: ${obj.type}\n" +
                            "鍒涘缓鏃堕棿: ${obj.createdAt}\n" +
                            "閿€姣佹椂闂? ${obj.destroyedAt}\n" +
                            "鍒涘缓鍫嗘爤:\n${obj.stackTrace.joinToString("\n")}"
                )
            }
        }
        
        // 娓呯悊宸插洖鏀剁殑瀵硅薄
        cleanupCollectedObjects()
    }
    
    /**
     * 璺熻釜鐨勫璞?
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
     * 娉勬紡绫诲瀷
     */
    enum class LeakType {
        ACTIVITY,
        FRAGMENT,
        VIEW_MODEL,
        RESOURCE,
        OTHER
    }
    
    /**
     * 娉勬紡淇℃伅
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
     * 娉勬紡缁熻
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
     * 娉勬紡鐩戝惉鍣ㄦ帴鍙?
     */
    interface LeakListener {
        fun onLeaksDetected(leaks: List<LeakInfo>)
    }
    
    companion object {
        private const val LEAK_DETECTION_DELAY_MS = 5000L // 5绉掑悗妫€鏌ユ硠婕?
        
        private val instanceMap = ConcurrentHashMap<Context, MemoryLeakDetector>()
        
        @JvmStatic
        fun getInstance(context: Context): MemoryLeakDetector {
            return instanceMap.getOrPut(context) {
                MemoryLeakDetector(context.applicationContext ?: context)
            }
        }
        
        /**
         * 蹇€熸鏌ctivity娉勬紡
         */
        @JvmStatic
        fun checkActivityLeak(activity: Activity): Boolean {
            val detector = getInstance(activity)
            detector.trackActivity(activity)
            
            // 绠€鍗曟鏌ワ細濡傛灉Activity宸茬粡onDestroy浣嗘湭琚洖鏀讹紝鍙兘娉勬紡
            return detector.getLeakStats().hasLeaks
        }
        
        /**
         * 鑾峰彇鍏ㄥ眬娉勬紡缁熻
         */
        @JvmStatic
        fun getGlobalLeakStats(): Map<Context, LeakStats> {
            return instanceMap.mapValues { it.value.getLeakStats() }
        }
        
        /**
         * 娓呯悊鎵€鏈夋娴嬪櫒
         */
        @JvmStatic
        fun cleanupAll() {
            instanceMap.values.forEach { it.stopMonitoring() }
            instanceMap.clear()
        }
    }
}
