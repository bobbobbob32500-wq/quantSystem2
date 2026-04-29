package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Error
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Success
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class ActionItem(
    val key: String,
    val title: String,
    val description: String,
    val isDanger: Boolean = false,
    val isLongRunning: Boolean = false,
)

private data class ActionOverviewCard(
    val title: String,
    val value: String,
    val subtitle: String,
)

@Composable
fun ActionsScreen(
    isActionRunning: Boolean,
    runningAction: String?,
    actionElapsedSeconds: Int,
    actionProgress: Float,
    onGeneratePlan: () -> Unit,
    onRunStockSelection: () -> Unit,
    onStartRuntime: () -> Unit,
    onStopRuntime: () -> Unit,
    onGenerateReview: () -> Unit,
    onRefresh: () -> Unit,
) {
    var pendingAction by remember { mutableStateOf<ActionItem?>(null) }

    val actionItems = remember {
        listOf(
            ActionItem("generate_plan", "生成计划", "生成当日计划并回写到总览与历史。", isLongRunning = true),
            ActionItem("run_stock_selection", "执行选股", "运行最新候选池选股流程。"),
            ActionItem("start_monitor_runtime", "启动监控运行时", "启动后端监控运行服务。"),
            ActionItem("stop_monitor_runtime", "停止监控运行时", "停止后端监控运行服务。", isDanger = true),
            ActionItem("generate_post_market_review", "生成收盘复盘", "执行收盘复盘并更新报告。", isLongRunning = true),
        )
    }
    val overviewCards = remember(isActionRunning, runningAction, actionElapsedSeconds, actionProgress) {
        listOf(
            ActionOverviewCard("状态", if (isActionRunning) "执行中" else "空闲", if (isActionRunning) actionTitle(runningAction) else "可发起新动作"),
            ActionOverviewCard("时长", "${actionElapsedSeconds}s", if (isActionRunning) "实时更新" else "等待执行"),
            ActionOverviewCard("进度", "${(actionProgress.coerceIn(0f, 1f) * 100).toInt()}%", if (isActionRunning) "当前任务" else "暂无任务"),
        )
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            TopBar(
                title = "动作中心",
                subtitle = if (isActionRunning) {
                    "正在执行 ${actionTitle(runningAction)}，这里是当前最重要的操作面板。"
                } else {
                    "关键动作集中在这里，先确认，再执行。"
                },
                eyebrow = "Action Desk",
            )
        }

        item {
            HeroSection(
                title = "动作面板",
                value = if (isActionRunning) "执行中" else "待执行",
                subtitle = if (isActionRunning) "已耗时 $actionElapsedSeconds 秒" else "当前没有进行中的后台动作。",
                stats = listOf(
                    Triple("进度", "${(actionProgress.coerceIn(0f, 1f) * 100).toInt()}%", ""),
                    Triple("运行", if (isActionRunning) "1" else "0", ""),
                    Triple("动作", actionItems.size.toString(), ""),
                ),
            )
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                overviewCards.forEach { card ->
                    ActionOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                }
            }
        }

        if (isActionRunning) {
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Surface),
                    shape = RoundedCornerShape(24.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
                ) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            text = "正在执行 ${actionTitle(runningAction)}",
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                            fontWeight = FontWeight.SemiBold,
                        )
                        LinearProgressIndicator(
                            progress = { actionProgress.coerceIn(0f, 1f) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .semantics {
                                    contentDescription = "动作执行进度"
                                    stateDescription = "${(actionProgress.coerceIn(0f, 1f) * 100).toInt()}%"
                                },
                        )
                        Text(
                            text = "执行中请留在本页观察状态，避免重复触发同一动作。",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary,
                        )
                    }
                }
            }
        }

        item {
            SecondaryButton(
                text = if (isActionRunning) "执行中..." else "刷新动作状态",
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isActionRunning,
            )
        }

        item { SectionHeader("可执行动作") }
        items(actionItems, key = { it.key }) { action ->
            ActionTaskCard(
                action = action,
                enabled = !isActionRunning,
                onClick = { pendingAction = action },
            )
        }
    }

    pendingAction?.let { action ->
        AlertDialog(
            onDismissRequest = { pendingAction = null },
            title = { Text("确认执行") },
            text = {
                Text(
                    buildString {
                        append("现在执行“${action.title}”吗？")
                        if (action.isLongRunning) append("\n该动作可能耗时 1-2 分钟。")
                        if (action.isDanger) append("\n该动作可能会中断正在运行的服务。")
                    },
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        when (action.key) {
                            "generate_plan" -> onGeneratePlan()
                            "run_stock_selection" -> onRunStockSelection()
                            "start_monitor_runtime" -> onStartRuntime()
                            "stop_monitor_runtime" -> onStopRuntime()
                            "generate_post_market_review" -> onGenerateReview()
                        }
                        pendingAction = null
                    },
                    enabled = !isActionRunning,
                ) {
                    Text("确认")
                }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingAction = null }) {
                    Text("取消")
                }
            },
        )
    }
}

@Composable
private fun ActionOverviewCardItem(
    card: ActionOverviewCard,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(22.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(card.title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(card.value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = TextPrimary)
            Text(card.subtitle, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

@Composable
private fun ActionTaskCard(
    action: ActionItem,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val tone = when {
        action.isDanger -> Error
        action.key == "run_stock_selection" -> Success
        action.key == "generate_plan" -> Primary
        else -> Primary.copy(alpha = 0.82f)
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = action.title,
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = action.description,
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            if (action.isLongRunning || action.isDanger) {
                StatusPill(
                    text = if (action.isDanger) "谨慎执行" else "可能耗时较长",
                    tone = if (action.isDanger) PillTone.Negative else PillTone.Neutral,
                )
            }
            Button(
                onClick = onClick,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics {
                        contentDescription = action.title
                        stateDescription = if (enabled) "可点击" else "执行中不可点击"
                    },
                enabled = enabled,
                colors = ButtonDefaults.buttonColors(containerColor = tone),
                shape = RoundedCornerShape(18.dp),
            ) {
                Text(action.title)
            }
        }
    }
}

private fun actionTitle(actionKey: String?): String {
    return when (actionKey) {
        "generate_plan" -> "生成计划"
        "run_stock_selection" -> "执行选股"
        "start_monitor_runtime" -> "启动监控运行时"
        "stop_monitor_runtime" -> "停止监控运行时"
        "generate_post_market_review" -> "生成收盘复盘"
        "push_selection_wecom" -> "推送候选池"
        null -> "动作"
        else -> actionKey
    }
}
