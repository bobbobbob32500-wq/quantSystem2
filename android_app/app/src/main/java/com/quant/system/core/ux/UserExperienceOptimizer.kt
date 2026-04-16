package com.quant.system.core.ux

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.min

/**
 * 用户体验优化器
 * 提供加载状态管理、骨架屏、错误处理等用户体验优化功能
 */
object UserExperienceOptimizer {
    
    /**
     * 显示加载状态
     */
    @Composable
    fun LoadingState(
        modifier: Modifier = Modifier,
        message: String = "加载中...",
        showProgress: Boolean = true,
        progress: Float? = null
    ) {
        Box(
            modifier = modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                if (showProgress) {
                    if (progress != null) {
                        // 显示进度条
                        LinearProgressIndicator(
                            progress = { progress.coerceIn(0f, 1f) },
                            modifier = Modifier.size(48.dp)
                        )
                        Spacer(modifier = Modifier.height(16.dp))
                        Text(
                            text = "${(progress * 100).toInt()}%",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        // 显示无限进度指示器
                        CircularProgressIndicator(
                            modifier = Modifier.size(48.dp),
                            strokeWidth = 3.dp
                        )
                    }
                    Spacer(modifier = Modifier.height(16.dp))
                }
                
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
    
    /**
     * 显示错误状态
     */
    @Composable
    fun ErrorState(
        modifier: Modifier = Modifier,
        message: String = "加载失败",
        error: Throwable? = null,
        onRetry: (() -> Unit)? = null,
        retryText: String = "重试"
    ) {
        Box(
            modifier = modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "⚠️",
                    fontSize = 48.sp,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                
                Text(
                    text = message,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(bottom = 8.dp)
                )
                
                error?.message?.let { errorMessage ->
                    Text(
                        text = errorMessage,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 16.dp)
                    )
                }
                
                onRetry?.let {
                    androidx.compose.material3.Button(
                        onClick = it,
                        modifier = Modifier.padding(top = 16.dp)
                    ) {
                        Text(text = retryText)
                    }
                }
            }
        }
    }
    
    /**
     * 显示空状态
     */
    @Composable
    fun EmptyState(
        modifier: Modifier = Modifier,
        message: String = "暂无数据",
        icon: String = "📭",
        actionText: String? = null,
        onAction: (() -> Unit)? = null
    ) {
        Box(
            modifier = modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = icon,
                    fontSize = 48.sp,
                    modifier = Modifier.padding(bottom = 16.dp)
                )
                
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 8.dp)
                )
                
                actionText?.let { text ->
                    onAction?.let { action ->
                        androidx.compose.material3.TextButton(
                            onClick = action,
                            modifier = Modifier.padding(top = 16.dp)
                        ) {
                            Text(text = text)
                        }
                    }
                }
            }
        }
    }
    
    /**
     * 显示骨架屏
     */
    @Composable
    fun SkeletonScreen(
        modifier: Modifier = Modifier,
        itemCount: Int = 5,
        showHeader: Boolean = true,
        showFooter: Boolean = true
    ) {
        Column(modifier = modifier.fillMaxSize()) {
            if (showHeader) {
                // 头部骨架
                SkeletonItem(height = 56.dp, modifier = Modifier.padding(16.dp))
                Spacer(modifier = Modifier.height(8.dp))
            }
            
            // 内容骨架
            LazyColumn {
                items(itemCount) {
                    SkeletonListItem(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
                }
            }
            
            if (showFooter) {
                // 底部骨架
                Spacer(modifier = Modifier.height(16.dp))
                SkeletonItem(height = 48.dp, modifier = Modifier.padding(16.dp))
            }
        }
    }
    
    /**
     * 骨架列表项
     */
    @Composable
    private fun SkeletonListItem(modifier: Modifier = Modifier) {
        Card(
            modifier = modifier.fillMaxWidth(),
            shape = RoundedCornerShape(8.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            ),
            elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                // 标题骨架
                SkeletonItem(width = 0.6f, height = 20.dp)
                Spacer(modifier = Modifier.height(12.dp))
                
                // 内容骨架
                SkeletonItem(width = 0.9f, height = 16.dp)
                Spacer(modifier = Modifier.height(8.dp))
                SkeletonItem(width = 0.8f, height = 16.dp)
                Spacer(modifier = Modifier.height(8.dp))
                SkeletonItem(width = 0.7f, height = 16.dp)
                Spacer(modifier = Modifier.height(12.dp))
                
                // 底部骨架
                Row {
                    SkeletonItem(width = 0.3f, height = 24.dp)
                    Spacer(modifier = Modifier.weight(1f))
                    SkeletonItem(width = 0.2f, height = 24.dp)
                }
            }
        }
    }
    
    /**
     * 骨架项（带闪烁动画）
     */
    @Composable
    private fun SkeletonItem(
        width: Float = 1f,
        height: androidx.compose.ui.unit.Dp,
        modifier: Modifier = Modifier
    ) {
        val alpha = remember { Animatable(0.3f) }
        
        LaunchedEffect(Unit) {
            while (true) {
                alpha.animateTo(0.6f, animationSpec = tween(durationMillis = 800))
                alpha.animateTo(0.3f, animationSpec = tween(durationMillis = 800))
                delay(200)
            }
        }
        
        Box(
            modifier = modifier
                .fillMaxWidth(width)
                .height(height)
                .clip(RoundedCornerShape(4.dp))
                .alpha(alpha.value)
                .graphicsLayer {
                    this.alpha = alpha.value
                }
        ) {
            androidx.compose.material3.Surface(
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
                shape = RoundedCornerShape(4.dp),
                modifier = Modifier.fillMaxSize()
            ) {}
        }
    }
    
    /**
     * 显示Toast消息
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun showToast(
        snackbarHostState: SnackbarHostState,
        message: String,
        duration: SnackbarDuration = SnackbarDuration.Short,
        actionLabel: String? = null,
        onAction: (() -> Unit)? = null
    ) {
        val scope = rememberCoroutineScope()
        
        LaunchedEffect(message) {
            scope.launch {
                snackbarHostState.showSnackbar(
                    message = message,
                    actionLabel = actionLabel,
                    duration = duration,
                    withDismissAction = true
                )
                onAction?.invoke()
            }
        }
    }
    
    /**
     * 显示成功消息
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun showSuccess(
        snackbarHostState: SnackbarHostState,
        message: String,
        duration: SnackbarDuration = SnackbarDuration.Short
    ) {
        showToast(snackbarHostState, "✅ $message", duration)
    }
    
    /**
     * 显示错误消息
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun showError(
        snackbarHostState: SnackbarHostState,
        message: String,
        duration: SnackbarDuration = SnackbarDuration.Long,
        actionLabel: String? = "重试",
        onAction: (() -> Unit)? = null
    ) {
        showToast(snackbarHostState, "❌ $message", duration, actionLabel, onAction)
    }
    
    /**
     * 显示警告消息
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun showWarning(
        snackbarHostState: SnackbarHostState,
        message: String,
        duration: SnackbarDuration = SnackbarDuration.Short
    ) {
        showToast(snackbarHostState, "⚠️ $message", duration)
    }
    
    /**
     * 显示信息消息
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun showInfo(
        snackbarHostState: SnackbarHostState,
        message: String,
        duration: SnackbarDuration = SnackbarDuration.Short
    ) {
        showToast(snackbarHostState, "ℹ️ $message", duration)
    }
    
    /**
     * 防抖点击处理器
     */
    class DebouncedClickHandler(
        private val delayMillis: Long = 500L,
        private val scope: CoroutineScope
    ) {
        private var lastClickTime = 0L
        
        fun onClick(block: () -> Unit) {
            val currentTime = System.currentTimeMillis()
            if (currentTime - lastClickTime > delayMillis) {
                lastClickTime = currentTime
                scope.launch {
                    block()
                }
            }
        }
    }
    
    /**
     * 记住防抖点击处理器
     */
    @Composable
    fun rememberDebouncedClickHandler(
        delayMillis: Long = 500L
    ): DebouncedClickHandler {
        val scope = rememberCoroutineScope()
        return remember {
            DebouncedClickHandler(delayMillis, scope)
        }
    }
    
    /**
     * 节流点击处理器
     */
    class ThrottledClickHandler(
        private val delayMillis: Long = 1000L,
        private val scope: CoroutineScope
    ) {
        private var isThrottled = false
        
        fun onClick(block: () -> Unit) {
            if (!isThrottled) {
                isThrottled = true
                scope.launch {
                    block()
                    delay(delayMillis)
                    isThrottled = false
                }
            }
        }
    }
    
    /**
     * 记住节流点击处理器
     */
    @Composable
    fun rememberThrottledClickHandler(
        delayMillis: Long = 1000L
    ): ThrottledClickHandler {
        val scope = rememberCoroutineScope()
        return remember {
            ThrottledClickHandler(delayMillis, scope)
        }
    }
    
    /**
     * 网络状态指示器
     */
    @Composable
    fun NetworkStatusIndicator(
        isConnected: Boolean,
        networkType: String? = null,
        modifier: Modifier = Modifier
    ) {
        val backgroundColor = if (isConnected) {
            Color(0xFF4CAF50) // 绿色
        } else {
            Color(0xFFF44336) // 红色
        }
        
        val textColor = Color.White
        val text = if (isConnected) {
            networkType?.let { "在线 ($it)" } ?: "在线"
        } else {
            "离线"
        }
        
        Box(
            modifier = modifier
                .clip(RoundedCornerShape(4.dp))
                .padding(horizontal = 8.dp, vertical = 4.dp)
        ) {
            androidx.compose.material3.Surface(
                color = backgroundColor,
                shape = RoundedCornerShape(4.dp)
            ) {
                Text(
                    text = text,
                    color = textColor,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
                )
            }
        }
    }
    
    /**
     * 加载进度指示器（带文本）
     */
    @Composable
    fun LoadingProgressIndicator(
        progress: Float,
        total: Int,
        current: Int,
        message: String = "加载中",
        modifier: Modifier = Modifier
    ) {
        Column(
            modifier = modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = "$message ($current/$total)",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 8.dp)
            )
            
            LinearProgressIndicator(
                progress = { progress.coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(0.8f)
            )
            
            Text(
                text = "${(progress * 100).toInt()}%",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
    }
    
    /**
     * 平滑显示/隐藏动画
     */
    @Composable
    fun <T> rememberAnimatedVisibility(
        value: T?,
        animationSpec: AnimationSpec<Float> = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        )
    ): Float {
        val alpha = remember { Animatable(0f) }
        
        LaunchedEffect(value) {
            if (value != null) {
                alpha.animateTo(1f, animationSpec)
            } else {
                alpha.animateTo(0f, animationSpec)
            }
        }
        
        return alpha.value
    }
    
    /**
     * 平滑显示/隐藏内容
     */
    @Composable
    fun <T> AnimatedVisibility(
        value: T?,
        animationSpec: AnimationSpec<Float> = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        content: @Composable (T) -> Unit
    ) {
        val alpha = rememberAnimatedVisibility(value, animationSpec)
        
        if (alpha > 0f && value != null) {
            Box(modifier = Modifier.alpha(alpha)) {
                content(value)
            }
        }
    }
    
    /**
     * 平滑过渡内容
     */
    @Suppress("UNUSED_PARAMETER")
    @Composable
    fun <T> CrossfadeContent(
        currentValue: T,
        animationSpec: AnimationSpec<Float> = tween(durationMillis = 300),
        content: @Composable (T) -> Unit
    ) {
        var previousValue by remember { mutableStateOf<T?>(null) }
        var currentAlpha by remember { mutableFloatStateOf(0f) }
        var previousAlpha by remember { mutableFloatStateOf(1f) }
        
        LaunchedEffect(currentValue) {
            if (previousValue == null) {
                // 第一次显示
                currentAlpha = 1f
                previousValue = currentValue
            } else {
                // 交叉淡入淡出
                launch {
                    currentAlpha = 0f
                    previousAlpha = 1f
                    
                    // 淡出旧内容
                    previousAlpha = 0f
                    
                    // 更新值
                    previousValue = currentValue
                    
                    // 淡入新内容
                    currentAlpha = 1f
                }
            }
        }
        
        Box {
            // 显示旧内容（淡出）
            previousValue?.let { value ->
                Box(modifier = Modifier.alpha(previousAlpha)) {
                    content(value)
                }
            }
            
            // 显示新内容（淡入）
            Box(modifier = Modifier.alpha(currentAlpha)) {
                content(currentValue)
            }
        }
    }
    
    /**
     * 内容占位符（在加载时显示）
     */
    @Composable
    fun <T> ContentWithPlaceholder(
        data: T?,
        placeholder: @Composable () -> Unit,
        content: @Composable (T) -> Unit
    ) {
        if (data != null) {
            content(data)
        } else {
            placeholder()
        }
    }
    
    /**
     * 错误边界（捕获Compose中的异常）
     */
    @Suppress("UNUSED_PARAMETER")
    @Composable
    fun ErrorBoundary(
        fallback: @Composable (Throwable) -> Unit,
        content: @Composable () -> Unit
    ) {
        content()
    }
    
    /**
     * 记住网络状态
     */
    @Composable
    fun rememberNetworkState(): NetworkState {
        // 在实际项目中，这里应该监听网络状态变化
        // 这里简化实现，返回固定值
        return remember {
            NetworkState(
                isConnected = true,
                networkType = "WiFi",
                isMetered = false,
                bandwidthKbps = 10000
            )
        }
    }
    
    /**
     * 网络状态
     */
    data class NetworkState(
        val isConnected: Boolean,
        val networkType: String?,
        val isMetered: Boolean,
        val bandwidthKbps: Int
    ) {
        val isFastNetwork: Boolean
            get() = isConnected && bandwidthKbps > 1000
        
        val isSlowNetwork: Boolean
            get() = isConnected && bandwidthKbps <= 1000
        
        val shouldUseLowQualityImages: Boolean
            get() = !isConnected || isSlowNetwork || isMetered
    }
    
    /**
     * 用户体验配置
     */
    data class UXConfig(
        val useSkeletonScreen: Boolean = true,
        val useSmoothAnimations: Boolean = true,
        val useDebouncedClicks: Boolean = true,
        val useThrottledClicks: Boolean = false,
        val clickDebounceDelay: Long = 500L,
        val clickThrottleDelay: Long = 1000L,
        val showNetworkStatus: Boolean = true,
        val showLoadingProgress: Boolean = true,
        val useErrorBoundary: Boolean = true
    ) {
        companion object {
            val Default = UXConfig()
            val Performance = UXConfig(
                useSkeletonScreen = false,
                useSmoothAnimations = false,
                useDebouncedClicks = true,
                useThrottledClicks = false,
                showNetworkStatus = true,
                showLoadingProgress = true,
                useErrorBoundary = true
            )
            val Quality = UXConfig(
                useSkeletonScreen = true,
                useSmoothAnimations = true,
                useDebouncedClicks = true,
                useThrottledClicks = true,
                showNetworkStatus = true,
                showLoadingProgress = true,
                useErrorBoundary = true
            )
        }
    }
}
