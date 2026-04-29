package com.quant.system.core.data

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.quant.system.core.NotificationHelper
import com.quant.system.core.network.NetworkMonitor
import com.quant.system.core.network.NetworkMonitorImpl
import com.quant.system.core.network.NetworkQuality
import com.quant.system.core.signal.SignalNotificationPolicy
import com.quant.system.data.repository.DashboardRepository
import com.quant.system.data.repository.LocalCacheRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext

/**
 * 数据同步工作器
 * 在后台定期同步数据
 */
class DataSyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {
    
    override suspend fun doWork(): Result {
        return try {
            withContext(Dispatchers.IO) {
                val settings = com.quant.system.data.repository.SettingsRepository(applicationContext)
                val baseUrl = settings.getBaseUrl()
                if (baseUrl.isBlank()) {
                    return@withContext Result.failure()
                }

                val repo = DashboardRepository(applicationContext)
                val cache = LocalCacheRepository(applicationContext)
                val notifier = NotificationHelper(applicationContext)

                val previousKeys = cache.getDashboardSnapshot()
                    ?.signals
                    ?.latestItems
                    .orEmpty()
                    .mapNotNull(SignalNotificationPolicy::signalKey)
                    .toSet()

                val snapshot = repo.getDashboard(baseUrl).getOrElse { error ->
                    android.util.Log.e("DataSyncWorker", "后台同步失败: ${error.message}", error)
                    return@withContext Result.retry()
                }

                cache.saveDashboardSnapshot(snapshot)

                if (notifier.canPostNotifications()) {
                    val buyNews = snapshot.signals?.latestItems
                        .orEmpty()
                        .filter {
                            val key = SignalNotificationPolicy.signalKey(it) ?: return@filter false
                            key !in previousKeys && SignalNotificationPolicy.isBuySignal(it)
                        }
                    buyNews.firstOrNull()?.let { first ->
                        val title = SignalNotificationPolicy.buildTitle(first)
                        val content = if (buyNews.size == 1) {
                            SignalNotificationPolicy.buildContent(first)
                        } else {
                            "${first.tsCode.orEmpty()} 等${buyNews.size}只触发买点"
                        }
                        notifier.notifySignalUpdate(title, content)
                        settings.appendNotificationLog("BUY_SIGNAL_BG|$title|$content")
                    }
                }

                Result.success()
            }
        } catch (e: Exception) {
            android.util.Log.e("DataSyncWorker", "数据同步工作器异常: ${e.message}", e)
            Result.retry()
        }
    }
    
    companion object {
        const val WORK_NAME = "data_sync_work"
        
        /**
         * 检查是否应该执行同步
         */
        suspend fun shouldSync(context: Context): Boolean {
            return try {
                // 检查网络连接
                val networkMonitor = NetworkMonitorImpl(context)
                val networkState = networkMonitor.networkState.first()
                
                // 只在网络连接良好时同步
                when (NetworkMonitor.getNetworkQualityLevel(networkState.networkQuality)) {
                    NetworkQuality.EXCELLENT, NetworkQuality.GOOD, NetworkQuality.FAIR -> true
                    NetworkQuality.POOR, NetworkQuality.VERY_POOR, NetworkQuality.OFFLINE -> false
                }
            } catch (e: Exception) {
                false
            }
        }
        
        /**
         * 获取下次同步的建议时间（毫秒）
         */
        suspend fun getNextSyncDelay(context: Context): Long {
            return try {
                val networkMonitor = NetworkMonitorImpl(context)
                val networkState = networkMonitor.networkState.first()
                
                when (NetworkMonitor.getNetworkQualityLevel(networkState.networkQuality)) {
                    NetworkQuality.EXCELLENT -> 5 * 60 * 1000L // 5分钟
                    NetworkQuality.GOOD -> 10 * 60 * 1000L    // 10分钟
                    NetworkQuality.FAIR -> 15 * 60 * 1000L    // 15分钟
                    NetworkQuality.POOR -> 30 * 60 * 1000L    // 30分钟
                    NetworkQuality.VERY_POOR -> 60 * 60 * 1000L // 60分钟
                    NetworkQuality.OFFLINE -> 120 * 60 * 1000L // 120分钟
                }
            } catch (e: Exception) {
                15 * 60 * 1000L // 默认15分钟
            }
        }
    }
}
