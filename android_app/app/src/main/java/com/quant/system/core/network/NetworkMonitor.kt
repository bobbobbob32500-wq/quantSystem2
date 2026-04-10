package com.quant.system.core.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import androidx.annotation.RequiresApi
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

/**
 * 网络状态监测器
 * 实时监测网络连接状态和质量
 */
interface NetworkMonitor {
    /**
     * 获取当前网络状态
     */
    val isConnected: Boolean
    
    /**
     * 获取网络类型
     */
    val networkType: NetworkType
    
    /**
     * 获取网络质量（0-100）
     */
    val networkQuality: Int
    
    /**
     * 监听网络状态变化
     */
    val networkState: Flow<NetworkState>
    
    /**
     * 检查网络是否可用
     */
    fun isNetworkAvailable(): Boolean
    
    /**
     * 获取网络延迟（ms）
     */
    suspend fun getNetworkLatency(): Long
    
    /**
     * 获取网络带宽（kbps）
     */
    suspend fun getNetworkBandwidth(): Long
}

/**
 * 网络状态
 */
data class NetworkState(
    val isConnected: Boolean,
    val networkType: NetworkType,
    val networkQuality: Int,
    val latency: Long = -1,
    val bandwidth: Long = -1
)

/**
 * 网络类型
 */
enum class NetworkType {
    UNKNOWN,
    WIFI,
    CELLULAR,
    ETHERNET,
    VPN,
    BLUETOOTH,
    LOWPAN,
    WIFI_AWARE,
    OFFLINE
}

/**
 * 网络质量等级
 */
enum class NetworkQuality {
    EXCELLENT,    // 优秀 (80-100)
    GOOD,         // 良好 (60-79)
    FAIR,         // 一般 (40-59)
    POOR,         // 差 (20-39)
    VERY_POOR,    // 极差 (0-19)
    OFFLINE       // 离线
}

/**
 * 网络监测器实现
 */
class NetworkMonitorImpl(private val context: Context) : NetworkMonitor {
    private val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    
    override val isConnected: Boolean
        get() = checkConnection()
    
    override val networkType: NetworkType
        get() = getCurrentNetworkType()
    
    override val networkQuality: Int
        get() = calculateNetworkQuality()
    
    override val networkState: Flow<NetworkState> = callbackFlow {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            val networkCallback = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    trySend(getCurrentNetworkState())
                }
                
                override fun onLost(network: Network) {
                    trySend(getCurrentNetworkState())
                }
                
                override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) {
                    trySend(getCurrentNetworkState())
                }
                
                override fun onLinkPropertiesChanged(network: Network, linkProperties: android.net.LinkProperties) {
                    trySend(getCurrentNetworkState())
                }
            }
            
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
                .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
                .build()
            
            connectivityManager.registerNetworkCallback(request, networkCallback)
            
            // 发送初始状态
            trySend(getCurrentNetworkState())
            
            awaitClose {
                connectivityManager.unregisterNetworkCallback(networkCallback)
            }
        } else {
            // Android N以下版本使用轮询方式
            val interval = 5000L // 5秒轮询一次
            val job = kotlinx.coroutines.launch {
                while (isActive) {
                    trySend(getCurrentNetworkState())
                    kotlinx.coroutines.delay(interval)
                }
            }
            
            awaitClose {
                job.cancel()
            }
        }
    }.distinctUntilChanged { old, new ->
        old.isConnected == new.isConnected && old.networkType == new.networkType
    }.map { state ->
        // 异步计算网络质量指标
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val latency = getNetworkLatency()
            val bandwidth = getNetworkBandwidth()
            state.copy(latency = latency, bandwidth = bandwidth)
        }
    }
    
    private fun checkConnection(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val network = connectivityManager.activeNetwork
            val capabilities = connectivityManager.getNetworkCapabilities(network)
            capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        } else {
            @Suppress("DEPRECATION")
            val networkInfo = connectivityManager.activeNetworkInfo
            networkInfo?.isConnectedOrConnecting == true
        }
    }
    
    private fun getCurrentNetworkType(): NetworkType {
        if (!checkConnection()) return NetworkType.OFFLINE
        
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val network = connectivityManager.activeNetwork
            val capabilities = connectivityManager.getNetworkCapabilities(network)
            
            when {
                capabilities == null -> NetworkType.UNKNOWN
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkType.WIFI
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> NetworkType.CELLULAR
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> NetworkType.ETHERNET
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> NetworkType.VPN
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) -> NetworkType.BLUETOOTH
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_LOWPAN) -> NetworkType.LOWPAN
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI_AWARE) -> NetworkType.WIFI_AWARE
                else -> NetworkType.UNKNOWN
            }
        } else {
            @Suppress("DEPRECATION")
            val networkInfo = connectivityManager.activeNetworkInfo
            when (networkInfo?.type) {
                ConnectivityManager.TYPE_WIFI -> NetworkType.WIFI
                ConnectivityManager.TYPE_MOBILE -> NetworkType.CELLULAR
                ConnectivityManager.TYPE_ETHERNET -> NetworkType.ETHERNET
                ConnectivityManager.TYPE_VPN -> NetworkType.VPN
                ConnectivityManager.TYPE_BLUETOOTH -> NetworkType.BLUETOOTH
                else -> NetworkType.UNKNOWN
            }
        }
    }
    
    private fun calculateNetworkQuality(): Int {
        if (!checkConnection()) return 0
        
        return when (networkType) {
            NetworkType.WIFI -> 85
            NetworkType.ETHERNET -> 95
            NetworkType.CELLULAR -> {
                // 根据信号强度估算质量
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    val network = connectivityManager.activeNetwork
                    val capabilities = connectivityManager.getNetworkCapabilities(network)
                    val signalStrength = capabilities?.getSignalStrength()
                    when {
                        signalStrength == null -> 50
                        signalStrength >= -70 -> 80  // 强信号
                        signalStrength >= -85 -> 60  // 中等信号
                        signalStrength >= -100 -> 40 // 弱信号
                        else -> 20                   // 极弱信号
                    }
                } else {
                    60 // 默认中等质量
                }
            }
            NetworkType.VPN -> 70
            else -> 50
        }
    }
    
    override fun isNetworkAvailable(): Boolean = checkConnection()
    
    override suspend fun getNetworkLatency(): Long {
        return if (!checkConnection()) {
            -1L
        } else {
            // 简化的延迟测试 - 实际项目中可以使用ping或HTTP请求测试
            when (networkType) {
                NetworkType.WIFI -> 20L
                NetworkType.ETHERNET -> 10L
                NetworkType.CELLULAR -> 100L
                NetworkType.VPN -> 150L
                else -> 200L
            }
        }
    }
    
    override suspend fun getNetworkBandwidth(): Long {
        return if (!checkConnection()) {
            -1L
        } else {
            // 简化的带宽估算
            when (networkType) {
                NetworkType.WIFI -> 50000L // 50 Mbps
                NetworkType.ETHERNET -> 100000L // 100 Mbps
                NetworkType.CELLULAR -> 10000L // 10 Mbps
                NetworkType.VPN -> 20000L // 20 Mbps
                else -> 5000L // 5 Mbps
            }
        }
    }
    
    private fun getCurrentNetworkState(): NetworkState {
        return NetworkState(
            isConnected = isConnected,
            networkType = networkType,
            networkQuality = networkQuality
        )
    }
    
    companion object {
        /**
         * 根据网络质量获取质量等级
         */
        fun getNetworkQualityLevel(quality: Int): NetworkQuality {
            return when {
                quality <= 0 -> NetworkQuality.OFFLINE
                quality < 20 -> NetworkQuality.VERY_POOR
                quality < 40 -> NetworkQuality.POOR
                quality < 60 -> NetworkQuality.FAIR
                quality < 80 -> NetworkQuality.GOOD
                else -> NetworkQuality.EXCELLENT
            }
        }
        
        /**
         * 根据网络类型和质量获取建议的重试延迟
         */
        fun getSuggestedRetryDelay(networkType: NetworkType, quality: Int): Long {
            val baseDelay = when (getNetworkQualityLevel(quality)) {
                NetworkQuality.EXCELLENT -> 1000L
                NetworkQuality.GOOD -> 2000L
                NetworkQuality.FAIR -> 3000L
                NetworkQuality.POOR -> 5000L
                NetworkQuality.VERY_POOR -> 10000L
                NetworkQuality.OFFLINE -> 30000L
            }
            
            // 根据网络类型调整
            return when (networkType) {
                NetworkType.CELLULAR -> baseDelay * 2
                NetworkType.VPN -> baseDelay * 3
                else -> baseDelay
            }
        }
        
        /**
         * 根据网络质量获取建议的超时时间
         */
        fun getSuggestedTimeout(networkType: NetworkType, quality: Int): Long {
            val baseTimeout = when (getNetworkQualityLevel(quality)) {
                NetworkQuality.EXCELLENT -> 10000L
                NetworkQuality.GOOD -> 15000L
                NetworkQuality.FAIR -> 20000L
                NetworkQuality.POOR -> 30000L
                NetworkQuality.VERY_POOR -> 45000L
                NetworkQuality.OFFLINE -> 60000L
            }
            
            // 根据网络类型调整
            return when (networkType) {
                NetworkType.CELLULAR -> baseTimeout * 2
                NetworkType.VPN -> baseTimeout * 3
                else -> baseTimeout
            }
        }
    }
}