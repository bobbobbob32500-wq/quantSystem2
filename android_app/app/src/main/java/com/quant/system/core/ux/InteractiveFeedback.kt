package com.quant.system.core.ux

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 交互反馈组件
 * 提供按钮反馈、确认对话框、操作反馈等交互优化
 */
object InteractiveFeedback {
    
    /**
     * 增强型按钮（带点击反馈）
     */
    @Composable
    fun EnhancedButton(
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
        enabled: Boolean = true,
        isLoading: Boolean = false,
        showSuccess: Boolean = false,
        showError: Boolean = false,
        successDuration: Long = 1000L,
        errorDuration: Long = 2000L,
        scaleOnClick: Boolean = true,
        rippleEnabled: Boolean = true,
        content: @Composable () -> Unit
    ) {
        val scope = rememberCoroutineScope()
        val scale = remember { Animatable(1f) }
        val alpha = remember { Animatable(1f) }
        var showSuccessState by remember { mutableStateOf(false) }
        var showErrorState by remember { mutableStateOf(false) }
        
        LaunchedEffect(showSuccess) {
            if (showSuccess) {
                showSuccessState = true
                delay(successDuration)
                showSuccessState = false
            }
        }
        
        LaunchedEffect(showError) {
            if (showError) {
                showErrorState = true
                delay(errorDuration)
                showErrorState = false
            }
        }
        
        Box(
            modifier = modifier,
            contentAlignment = Alignment.Center
        ) {
            // 成功状态覆盖层
            if (showSuccessState) {
                Surface(
                    color = Color.Green.copy(alpha = 0.2f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.matchParentSize()
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Default.Check,
                            contentDescription = "成功",
                            tint = Color.Green,
                            modifier = Modifier.size(24.dp)
                        )
                    }
                }
            }
            
            // 错误状态覆盖层
            if (showErrorState) {
                Surface(
                    color = Color.Red.copy(alpha = 0.2f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.matchParentSize()
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Default.Error,
                            contentDescription = "错误",
                            tint = Color.Red,
                            modifier = Modifier.size(24.dp)
                        )
                    }
                }
            }
            
            // 加载状态覆盖层
            if (isLoading) {
                Surface(
                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.7f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.matchParentSize()
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        androidx.compose.material3.CircularProgressIndicator(
                            strokeWidth = 2.dp,
                            modifier = Modifier.size(20.dp)
                        )
                    }
                }
            }
            
            Button(
                onClick = {
                    if (enabled && !isLoading) {
                        if (scaleOnClick) {
                            scope.launch {
                                scale.animateTo(0.95f, animationSpec = tween(durationMillis = 50))
                                scale.animateTo(1f, animationSpec = spring(
                                    dampingRatio = Spring.DampingRatioMediumBouncy,
                                    stiffness = Spring.StiffnessLow
                                ))
                            }
                        }
                        onClick()
                    }
                },
                enabled = enabled && !isLoading,
                modifier = Modifier
                    .scale(scale.value)
                    .alpha(alpha.value),
                colors = if (!enabled) {
                    ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                } else {
                    ButtonDefaults.buttonColors()
                },
                interactionSource = remember { MutableInteractionSource() }
            ) {
                content()
            }
        }
    }
    
    /**
     * 确认对话框
     */
    @Composable
    fun ConfirmationDialog(
        title: String,
        message: String,
        onConfirm: () -> Unit,
        onDismiss: () -> Unit,
        confirmText: String = "确认",
        dismissText: String = "取消",
        icon: ImageVector? = null,
        iconTint: Color = MaterialTheme.colorScheme.primary,
        destructive: Boolean = false
    ) {
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                dismissOnBackPress = true,
                dismissOnClickOutside = true
            )
        ) {
            Card(
                modifier = Modifier
                    .fillMaxWidth(0.9f)
                    .padding(16.dp),
                shape = RoundedCornerShape(16.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    // 图标
                    icon?.let {
                        Icon(
                            imageVector = it,
                            contentDescription = null,
                            tint = iconTint,
                            modifier = Modifier
                                .size(48.dp)
                                .padding(bottom = 16.dp)
                        )
                    }
                    
                    // 标题
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                    
                    // 消息
                    Text(
                        text = message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 24.dp)
                    )
                    
                    // 按钮
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = androidx.compose.foundation.layout.Arrangement.End
                    ) {
                        Button(
                            onClick = onDismiss,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                                contentColor = MaterialTheme.colorScheme.onSurfaceVariant
                            ),
                            modifier = Modifier.padding(end = 8.dp)
                        ) {
                            Text(text = dismissText)
                        }
                        
                        Button(
                            onClick = {
                                onConfirm()
                                onDismiss()
                            },
                            colors = if (destructive) {
                                ButtonDefaults.buttonColors(
                                    containerColor = MaterialTheme.colorScheme.error,
                                    contentColor = MaterialTheme.colorScheme.onError
                                )
                            } else {
                                ButtonDefaults.buttonColors()
                            }
                        ) {
                            Text(text = confirmText)
                        }
                    }
                }
            }
        }
    }
    
    /**
     * 操作反馈对话框
     */
    @Composable
    fun ActionFeedbackDialog(
        type: FeedbackType,
        title: String,
        message: String,
        onDismiss: () -> Unit,
        autoDismiss: Boolean = true,
        autoDismissDelay: Long = 2000L
    ) {
        if (autoDismiss) {
            LaunchedEffect(Unit) {
                delay(autoDismissDelay)
                onDismiss()
            }
        }
        
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                dismissOnBackPress = false,
                dismissOnClickOutside = false
            )
        ) {
            Card(
                modifier = Modifier
                    .fillMaxWidth(0.8f)
                    .padding(16.dp),
                shape = RoundedCornerShape(16.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    // 图标
                    Icon(
                        imageVector = type.icon,
                        contentDescription = null,
                        tint = type.color,
                        modifier = Modifier
                            .size(48.dp)
                            .padding(bottom = 16.dp)
                    )
                    
                    // 标题
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                    
                    // 消息
                    Text(
                        text = message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        modifier = Modifier.padding(bottom = 16.dp)
                    )
                    
                    if (!autoDismiss) {
                        Button(
                            onClick = onDismiss,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(text = "确定")
                        }
                    }
                }
            }
        }
    }
    
    /**
     * 反馈类型
     */
    enum class FeedbackType(
        val icon: ImageVector,
        val color: Color
    ) {
        SUCCESS(Icons.Default.Check, Color(0xFF4CAF50)),
        ERROR(Icons.Default.Error, Color(0xFFF44336)),
        WARNING(Icons.Default.Warning, Color(0xFFFF9800)),
        INFO(Icons.Default.Info, Color(0xFF2196F3))
    }
    
    /**
     * 浮动操作按钮（带反馈）
     */
    @Composable
    fun FloatingActionButton(
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
        icon: ImageVector,
        contentDescription: String? = null,
        backgroundColor: Color = MaterialTheme.colorScheme.primary,
        contentColor: Color = MaterialTheme.colorScheme.onPrimary,
        elevation: Dp = 6.dp,
        showBadge: Boolean = false,
        badgeCount: Int = 0,
        badgeColor: Color = Color.Red,
        scaleOnClick: Boolean = true
    ) {
        val scope = rememberCoroutineScope()
        val scale = remember { Animatable(1f) }
        val rotation = remember { Animatable(0f) }
        
        Box(
            modifier = modifier,
            contentAlignment = Alignment.Center
        ) {
            // 徽章
            if (showBadge && badgeCount > 0) {
                Box(
                    modifier = Modifier
                        .size(20.dp)
                        .clip(CircleShape)
                        .background(badgeColor)
                        .align(Alignment.TopEnd)
                        .offset(x = 8.dp, y = (-8).dp)
                ) {
                    Text(
                        text = if (badgeCount > 99) "99+" else badgeCount.toString(),
                        color = Color.White,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.align(Alignment.Center)
                    )
                }
            }
            
            Surface(
                modifier = Modifier
                    .size(56.dp)
                    .clip(CircleShape)
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null
                    ) {
                        if (scaleOnClick) {
                            scope.launch {
                                scale.animateTo(0.9f, animationSpec = tween(durationMillis = 50))
                                scale.animateTo(1f, animationSpec = spring(
                                    dampingRatio = Spring.DampingRatioMediumBouncy,
                                    stiffness = Spring.StiffnessLow
                                ))
                                rotation.animateTo(rotation.value + 90f, animationSpec = spring())
                            }
                        }
                        onClick()
                    }
                    .scale(scale.value)
                    .graphicsLayer {
                        rotationZ = rotation.value
                    },
                color = backgroundColor,
                contentColor = contentColor,
                shadowElevation = elevation
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = icon,
                        contentDescription = contentDescription,
                        modifier = Modifier.size(24.dp)
                    )
                }
            }
        }
    }
    
    /**
     * 下拉刷新指示器
     */
    @Composable
    fun PullToRefreshIndicator(
        isRefreshing: Boolean,
        pullProgress: Float,
        modifier: Modifier = Modifier
    ) {
        val rotation = remember { Animatable(0f) }
        val scale = remember { Animatable(1f) }
        
        LaunchedEffect(isRefreshing) {
            if (isRefreshing) {
                // 旋转动画
                launch {
                    while (isRefreshing) {
                        rotation.animateTo(
                            targetValue = rotation.value + 360f,
                            animationSpec = tween(durationMillis = 1000)
                        )
                    }
                }
                // 缩放动画
                launch {
                    scale.animateTo(1.2f, animationSpec = spring())
                    scale.animateTo(1f, animationSpec = spring())
                }
            } else {
                rotation.snapTo(0f)
                scale.snapTo(1f)
            }
        }
        
        Box(
            modifier = modifier
                .fillMaxWidth()
                .height(64.dp),
            contentAlignment = Alignment.Center
        ) {
            if (isRefreshing || pullProgress > 0) {
                val alpha = (pullProgress * 2).coerceIn(0f, 1f)
                
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .alpha(alpha)
                        .graphicsLayer {
                            rotationZ = rotation.value
                            scaleX = scale.value
                            scaleY = scale.value
                        }
                ) {
                    androidx.compose.material3.CircularProgressIndicator(
                        strokeWidth = 3.dp,
                        modifier = Modifier.fillMaxSize()
                    )
                }
                
                if (isRefreshing) {
                    Text(
                        text = "刷新中...",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 48.dp)
                    )
                } else if (pullProgress >= 1f) {
                    Text(
                        text = "释放刷新",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 48.dp)
                    )
                } else {
                    Text(
                        text = "下拉刷新",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 48.dp)
                    )
                }
            }
        }
    }
    
    /**
     * 上拉加载更多指示器
     */
    @Composable
    fun LoadMoreIndicator(
        isLoading: Boolean,
        hasMore: Boolean,
        modifier: Modifier = Modifier
    ) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .height(64.dp),
            contentAlignment = Alignment.Center
        ) {
            if (isLoading) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.CircularProgressIndicator(
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "加载更多...",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else if (hasMore) {
                Text(
                    text = "上拉加载更多",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                Text(
                    text = "没有更多数据了",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
    
    /**
     * 触摸反馈表面
     */
    @Composable
    fun TouchFeedbackSurface(
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
        enabled: Boolean = true,
        scaleOnClick: Boolean = true,
        rippleEnabled: Boolean = true,
        backgroundColor: Color = MaterialTheme.colorScheme.surface,
        contentColor: Color = MaterialTheme.colorScheme.onSurface,
        elevation: Dp = 0.dp,
        borderWidth: Dp = 0.dp,
        borderColor: Color = Color.Transparent,
        shape: androidx.compose.ui.graphics.Shape = RoundedCornerShape(8.dp),
        content: @Composable () -> Unit
    ) {
        val scope = rememberCoroutineScope()
        val scale = remember { Animatable(1f) }
        val alpha = remember { Animatable(1f) }
        
        Surface(
            modifier = modifier
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = if (rippleEnabled) {
                        androidx.compose.material.ripple.rememberRipple()
                    } else {
                        null
                    },
                    enabled = enabled,
                    onClick = {
                        if (enabled) {
                            if (scaleOnClick) {
                                scope.launch {
                                    scale.animateTo(0.98f, animationSpec = tween(durationMillis = 50))
                                    scale.animateTo(1f, animationSpec = spring(
                                        dampingRatio = Spring.DampingRatioMediumBouncy,
                                        stiffness = Spring.StiffnessLow
                                    ))
                                }
                            }
                            onClick()
                        }
                    }
                )
                .scale(scale.value)
                .alpha(alpha.value),
            color = backgroundColor,
            contentColor = contentColor,
            shape = shape,
            tonalElevation = elevation,
            shadowElevation = elevation,
            border = if (borderWidth > 0.dp) {
                androidx.compose.foundation.BorderStroke(borderWidth, borderColor)
            } else {
                null
            }
        ) {
            content()
        }
    }
    
    /**
     * 长按菜单
     */
    @Composable
    fun LongPressMenu(
        items: List<MenuItem>,
        onDismiss: () -> Unit,
        modifier: Modifier = Modifier
    ) {
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                dismissOnBackPress = true,
                dismissOnClickOutside = true
            )
        ) {
            Card(
                modifier = modifier
                    .fillMaxWidth(0.8f)
                    .padding(16.dp),
                shape = RoundedCornerShape(16.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
            ) {
                Column(
                    modifier = Modifier.padding(vertical = 8.dp)
                ) {
                    items.forEachIndexed { index, item ->
                        TouchFeedbackSurface(
                            onClick = {
                                item.onClick()
                                onDismiss()
                            },
                            modifier = Modifier.fillMaxWidth(),
                            backgroundColor = if (item.destructive) {
                                MaterialTheme.colorScheme.errorContainer
                            } else {
                                MaterialTheme.colorScheme.surface
                            },
                            contentColor = if (item.destructive) {
                                MaterialTheme.colorScheme.onErrorContainer
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            }
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 16.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                item.icon?.let { icon ->
                                    Icon(
                                        imageVector = icon,
                                        contentDescription = item.label,
                                        modifier = Modifier
                                            .size(24.dp)
                                            .padding(end = 12.dp)
                                    )
                                }
                                Text(
                                    text = item.label,
                                    style = MaterialTheme.typography.bodyMedium,
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                        
                        if (index < items.size - 1) {
                            androidx.compose.material3.Divider(
                                modifier = Modifier.padding(horizontal = 16.dp),
                                thickness = 0.5.dp,
                                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.2f)
                            )
                        }
                    }
                }
            }
        }
    }
    
    /**
     * 菜单项
     */
    data class MenuItem(
        val label: String,
        val icon: ImageVector? = null,
        val onClick: () -> Unit,
        val destructive: Boolean = false
    )
    
    /**
     * 进度指示器（带文本）
     */
    @Composable
    fun ProgressIndicatorWithText(
        progress: Float,
        text: String,
        modifier: Modifier = Modifier,
        color: Color = MaterialTheme.colorScheme.primary,
        backgroundColor: Color = MaterialTheme.colorScheme.surfaceVariant
    ) {
        Column(
            modifier = modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(backgroundColor)
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(progress.coerceIn(0f, 1f))
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(color)
                )
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
    
    /**
     * 振动反馈（需要权限）
     */
    fun vibrate(context: android.content.Context, duration: Long = 50L) {
        try {
            val vibrator = context.getSystemService(android.content.Context.VIBRATOR_SERVICE) as? android.os.Vibrator
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                vibrator?.vibrate(android.os.VibrationEffect.createOneShot(duration, android.os.VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(duration)
            }
        } catch (e: Exception) {
            // 忽略振动失败
        }
    }
    
    /**
     * 触觉反馈（需要权限）
     */
    fun hapticFeedback(context: android.content.Context, feedbackType: Int = android.view.HapticFeedbackConstants.CONTEXT_CLICK) {
        try {
            val view = android.view.View(context)
            view.performHapticFeedback(feedbackType)
        } catch (e: Exception) {
            // 忽略触觉反馈失败
        }
    }
}