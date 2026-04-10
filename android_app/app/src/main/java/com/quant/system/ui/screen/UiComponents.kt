package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.ExperimentalMaterialApi
import androidx.compose.material.pullrefresh.PullRefreshIndicator
import androidx.compose.material.pullrefresh.pullRefresh
import androidx.compose.material.pullrefresh.rememberPullRefreshState
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Error
import com.quant.system.ui.theme.ErrorDark
import com.quant.system.ui.theme.ErrorLight
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.PrimaryDark
import com.quant.system.ui.theme.PrimaryLight
import com.quant.system.ui.theme.Success
import com.quant.system.ui.theme.SuccessDark
import com.quant.system.ui.theme.SuccessLight
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import com.quant.system.ui.theme.Warning
import com.quant.system.ui.theme.WarningDark
import com.quant.system.ui.theme.WarningLight

enum class PillTone {
    Positive,
    Negative,
    Neutral,
}

private val CornerSmall = 12.dp
private val CornerMedium = 16.dp
private val CornerLarge = 20.dp
private val MinTouchHeight = 48.dp

@OptIn(ExperimentalMaterialApi::class)
@Composable
fun RefreshContainer(
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    content: @Composable () -> Unit,
) {
    val refreshState = rememberPullRefreshState(
        refreshing = isRefreshing,
        onRefresh = onRefresh,
    )
    Box(
        modifier = Modifier
            .fillMaxSize()
            .pullRefresh(refreshState),
    ) {
        content()
        PullRefreshIndicator(
            refreshing = isRefreshing,
            state = refreshState,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .semantics {
                    contentDescription = "下拉刷新指示器"
                    stateDescription = if (isRefreshing) "刷新中" else "空闲"
                },
        )
    }
}

@Composable
fun ScreenHeader(
    title: String,
    subtitle: String,
    actions: @Composable () -> Unit = {},
) = TopBar(title, subtitle, actions)

@Composable
fun TopBar(
    title: String,
    subtitle: String,
    actions: @Composable () -> Unit = {},
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Surface)
            .padding(top = 60.dp, start = 20.dp, end = 20.dp, bottom = 16.dp)
            .semantics { contentDescription = "$title，$subtitle" },
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.headlineSmall,
                    color = TextPrimary,
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    fontWeight = FontWeight.Medium,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                actions()
            }
        }
    }
}

@Composable
fun SectionHeader(
    title: String,
    action: @Composable (() -> Unit)? = null,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .semantics { contentDescription = "分区：$title" },
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = TextPrimary,
            fontWeight = FontWeight.Bold,
        )
        action?.invoke()
    }
}

@Composable
fun EmptyStateCard(message: String) {
    DetailCard(title = "暂无数据", lines = listOf(message))
}

@Composable
fun ValueCard(title: String, value: String, detail: String) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "$title，$value。$detail" },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(CornerMedium),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = TextPrimary)
            Text(value, style = MaterialTheme.typography.headlineSmall, color = TextPrimary)
            Text(detail, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

@Composable
fun DetailCard(title: String, lines: List<String>) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = buildString {
                    append(title)
                    if (lines.isNotEmpty()) {
                        append("。")
                        append(lines.joinToString("。"))
                    }
                }
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(CornerMedium),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = TextPrimary)
            lines.filter { it.isNotBlank() }.forEach { line ->
                Text(line, style = MaterialTheme.typography.bodyMedium, color = TextSecondary)
            }
        }
    }
}

@Composable
fun NoticeBanner(
    message: String,
    type: NoticeType,
    onRetry: (() -> Unit)? = null,
) {
    val bgColor = when (type) {
        NoticeType.Success -> SuccessLight
        NoticeType.Error -> ErrorLight
        NoticeType.Info -> WarningLight
    }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = message
                stateDescription = when (type) {
                    NoticeType.Success -> "成功提示"
                    NoticeType.Error -> "错误提示"
                    NoticeType.Info -> "信息提示"
                }
            },
        colors = CardDefaults.cardColors(containerColor = bgColor),
        shape = RoundedCornerShape(CornerLarge),
        elevation = CardDefaults.cardElevation(0.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = message,
                color = TextPrimary,
                style = MaterialTheme.typography.bodyMedium,
            )
            if (type == NoticeType.Error && onRetry != null) {
                TextButton(
                    onClick = onRetry,
                    modifier = Modifier
                        .align(Alignment.End)
                        .semantics {
                            contentDescription = "重试"
                            role = Role.Button
                        },
                ) {
                    Text("重试")
                }
            }
        }
    }
}

@Composable
fun StatusPill(text: String, tone: PillTone) {
    val background = when (tone) {
        PillTone.Positive -> SuccessLight
        PillTone.Negative -> ErrorLight
        PillTone.Neutral -> WarningLight
    }
    val foreground = when (tone) {
        PillTone.Positive -> SuccessDark
        PillTone.Negative -> ErrorDark
        PillTone.Neutral -> WarningDark
    }
    Box(
        modifier = Modifier
            .clip(CircleShape)
            .background(background)
            .padding(horizontal = 12.dp, vertical = 7.dp)
            .semantics {
                contentDescription = text
                stateDescription = when (tone) {
                    PillTone.Positive -> "正向"
                    PillTone.Negative -> "风险"
                    PillTone.Neutral -> "中性"
                }
            },
    ) {
        Text(
            text = text,
            color = foreground,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
fun ScoreBar(progress: Float, tone: PillTone) {
    val barColor = when (tone) {
        PillTone.Positive -> Success
        PillTone.Negative -> Error
        PillTone.Neutral -> Warning
    }
    val value = progress.coerceIn(0f, 1f)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(8.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(SurfaceVariant)
            .semantics {
                contentDescription = "评分进度"
                stateDescription = "${(value * 100).toInt()}%"
            },
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(value)
                .height(8.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(barColor),
        )
    }
}

@Composable
fun HeroSection(
    title: String,
    value: String,
    subtitle: String,
    percentage: String? = null,
    isPositive: Boolean = true,
    stats: List<Triple<String, String, String>>,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "$title，$value。$subtitle"
            },
        colors = CardDefaults.cardColors(containerColor = Primary),
        shape = RoundedCornerShape(CornerLarge),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.8f),
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = value,
                    style = MaterialTheme.typography.headlineSmall,
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    fontSize = 32.sp,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.75f),
                )
                percentage?.let {
                    val pillBg = if (isPositive) Color.White.copy(alpha = 0.15f) else ErrorLight.copy(alpha = 0.3f)
                    val pillColor = if (isPositive) Color.White else Error
                    Box(
                        modifier = Modifier
                            .clip(CircleShape)
                            .background(pillBg)
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    ) {
                        Text(
                            text = it,
                            color = pillColor,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                stats.forEach { (label, itemValue, _) ->
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color.White.copy(alpha = 0.15f))
                            .padding(vertical = 12.dp, horizontal = 8.dp)
                            .semantics { contentDescription = "$label，$itemValue" },
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = itemValue,
                                style = MaterialTheme.typography.titleLarge,
                                color = Color.White,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = label,
                                style = MaterialTheme.typography.labelSmall,
                                color = Color.White.copy(alpha = 0.8f),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun HealthCard(
    status: String,
    subtitle: String,
    isHealthy: Boolean,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "系统健康状态：$status。$subtitle"
                stateDescription = if (isHealthy) "健康" else "异常"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(CornerMedium),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(RoundedCornerShape(CornerSmall))
                    .background(if (isHealthy) SuccessLight else ErrorLight),
                contentAlignment = Alignment.Center,
            ) {
                Text(if (isHealthy) "✓" else "!", fontSize = 20.sp)
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = status,
                    style = MaterialTheme.typography.titleSmall,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            StatusPill(
                text = if (isHealthy) "健康" else "异常",
                tone = if (isHealthy) PillTone.Positive else PillTone.Negative,
            )
        }
    }
}

@Composable
fun QuickActions(
    actions: List<QuickAction>,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        actions.forEach { action ->
            val clickableModifier = if (action.onClick != null) {
                Modifier
                    .clickable(onClick = action.onClick)
                    .semantics {
                        role = Role.Button
                        contentDescription = action.label
                        stateDescription = "可点击"
                    }
            } else {
                Modifier
            }
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(CornerSmall))
                    .then(clickableModifier)
                    .padding(vertical = 8.dp, horizontal = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(48.dp)
                    .clip(RoundedCornerShape(CornerMedium))
                        .background(action.background ?: Primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(action.icon, fontSize = 22.sp)
                }
                Text(
                    text = action.label,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

data class QuickAction(
    val icon: String,
    val label: String,
    val background: Color? = null,
    val onClick: (() -> Unit)? = null,
)

@Composable
fun StrategyTabs(
    strategies: List<Pair<String, String>>,
    selectedStrategy: String,
    onStrategySelected: (String) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(CornerSmall))
            .background(SurfaceVariant.copy(alpha = 0.5f))
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        strategies.forEach { (key, label) ->
            val isSelected = key == selectedStrategy
            Box(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(10.dp))
                    .background(if (isSelected) Surface else Color.Transparent)
                    .then(
                        if (!isSelected) {
                            Modifier.clickable { onStrategySelected(key) }
                        } else {
                            Modifier
                        },
                    )
                    .padding(horizontal = 14.dp, vertical = 10.dp)
                    .semantics {
                        role = Role.Tab
                        contentDescription = label
                        stateDescription = if (isSelected) "已选中" else "未选中"
                    },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (isSelected) PrimaryDark else TextSecondary,
                    fontWeight = if (isSelected) FontWeight.Bold else FontWeight.SemiBold,
                )
            }
        }
    }
}

@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    icon: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .heightIn(min = MinTouchHeight)
            .semantics {
                contentDescription = text
                role = Role.Button
                stateDescription = if (enabled) "可点击" else "不可点击"
            },
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = Primary,
            disabledContainerColor = PrimaryLight,
        ),
        shape = RoundedCornerShape(CornerSmall),
    ) {
        icon?.invoke()
        if (icon != null) {
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(text, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun SuccessButton(
    text: String,
    onClick: () -> Unit,
    icon: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .heightIn(min = MinTouchHeight)
            .semantics {
                contentDescription = text
                role = Role.Button
                stateDescription = if (enabled) "可点击" else "不可点击"
            },
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = Success,
            disabledContainerColor = SuccessLight,
        ),
        shape = RoundedCornerShape(CornerSmall),
    ) {
        icon?.invoke()
        if (icon != null) {
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(text, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .heightIn(min = MinTouchHeight)
            .semantics {
                contentDescription = text
                role = Role.Button
                stateDescription = if (enabled) "可点击" else "不可点击"
            },
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = Surface,
            contentColor = TextPrimary,
        ),
        shape = RoundedCornerShape(CornerSmall),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border),
    ) {
        Text(text, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun LoadingSkeletonCard(
    modifier: Modifier = Modifier,
    lines: Int = 3,
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "内容加载中"
                stateDescription = "请稍候"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(CornerMedium),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            repeat(lines) { index ->
                Box(
                    modifier = Modifier
                        .fillMaxWidth(if (index == lines - 1) 0.6f else 1f)
                        .height(14.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(SurfaceVariant),
                )
            }
        }
    }
}
