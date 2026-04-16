package com.quant.system.core.data

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.quant.system.core.network.NetworkMonitor
import com.quant.system.core.network.NetworkMonitorImpl
import com.quant.system.core.network.NetworkQuality
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
                // 获取基础URL
                val settings = com.quant.system.data.repository.SettingsRepository(applicationContext)
                val baseUrl = settings.getBaseUrl()
                
                if (baseUrl.isBlank()) {
                    return@withContext Result.failure()
                }
                
                // 创建数据同步优化器
                val syncOptimizer = DataSyncOptimizer(applicationContext)
                
                // 执行数据同步
                var syncSuccess = false
                
                syncOptimizer.startSync(
                    baseUrl = baseUrl,
                    onSuccess = { _ ->
                        // 同步成功，可以在这里处理数据
                        // 例如：更新本地数据库、发送通知等
                        syncSuccess = true
                    },
                    onError = { error ->
                        // 同步失败，记录错误日志
                        android.util.Log.e("DataSyncWorker", "数据同步失败: ${error.message}")
                    },
                    forceRefresh = false
                )
                
                // 等待同步完成（简化实现，实际应该使用回调或Flow）
                kotlinx.coroutines.delay(30000) // 最多等待30秒
                
                if (syncSuccess) {
                    Result.success()
                } else {
                    Result.retry()
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("DataSyncWorker", "数据同步工作器异常: ${e.message}", e)
            Result.failure()
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
