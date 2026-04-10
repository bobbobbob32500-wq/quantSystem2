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
import com.quant.system.ui.theme.Error
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Success
import com.quant.system.ui.theme.Surface
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
    val id: String,
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
            ActionItem(
                key = "generate_plan",
                title = "生成计划",
                description = "生成当日计划并更新概览。",
                isLongRunning = true,
            ),
            ActionItem(
                key = "run_stock_selection",
                title = "执行选股",
                description = "运行最新候选池选股流程。",
            ),
            ActionItem(
                key = "start_monitor_runtime",
                title = "启动监控运行时",
                description = "启动后端监控运行服务。",
            ),
            ActionItem(
                key = "stop_monitor_runtime",
                title = "停止监控运行时",
                description = "停止后端监控运行服务。",
                isDanger = true,
            ),
            ActionItem(
                key = "generate_post_market_review",
                title = "生成收盘复盘",
                description = "执行收盘复盘并更新报告。",
                isLongRunning = true,
            ),
        )
    }

    val overviewCards = remember(isActionRunning, runningAction, actionElapsedSeconds, actionProgress) {
        listOf(
            ActionOverviewCard(
                id = "status",
                title = "执行状态",
                value = if (isActionRunning) "执行中" else "空闲",
                subtitle = if (isActionRunning) actionTitle(runningAction) else "可发起新动作",
            ),
            ActionOverviewCard(
                id = "elapsed",
                title = "执行时长",
                value = "${actionElapsedSeconds}s",
                subtitle = if (isActionRunning) "实时更新" else "等待执行",
            ),
            ActionOverviewCard(
                id = "progress",
                title = "进度",
                value = "${(actionProgress.coerceIn(0f, 1f) * 100).toInt()}%",
                subtitle = if (isActionRunning) "当前任务进度" else "暂无进行中任务",
            ),
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(
                title = "动作中心",
                subtitle = if (isActionRunning) {
                    "执行中：${actionTitle(runningAction)}（${actionElapsedSeconds}s）"
                } else {
                    "关键动作需确认，避免误触发。"
                },
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
                    modifier = Modifier.fillMaxWidth().semantics {
                        contentDescription = "动作执行状态"
                        stateDescription = "执行中"
                    },
                    colors = CardDefaults.cardColors(containerColor = Surface),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            text = "正在执行 ${actionTitle(runningAction)}",
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                        )
                        LinearProgressIndicator(
                            progress = { actionProgress.coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth().semantics {
                                contentDescription = "动作执行进度"
                                stateDescription = "${(actionProgress.coerceIn(0f, 1f) * 100).toInt()}%"
                            },
                        )
                        Text(
                            text = "已耗时 $actionElapsedSeconds 秒，请在本页查看实时进度。",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary,
                        )
                    }
                }
            }
        }

        item {
            Button(
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth().semantics {
                    contentDescription = "刷新看板"
                    stateDescription = if (isActionRunning) "不可用" else "可用"
                },
                enabled = !isActionRunning,
            ) {
                Text(if (isActionRunning) "请稍候..." else "刷新看板")
            }
        }

        item { SectionHeader("可执行动作") }
        items(actionItems, key = { it.key }) { action ->
            val colors = when {
                action.isDanger -> ButtonDefaults.buttonColors(containerColor = Error)
                action.key == "run_stock_selection" -> ButtonDefaults.buttonColors(containerColor = Success)
                action.key == "generate_plan" -> ButtonDefaults.buttonColors(containerColor = Primary)
                else -> ButtonDefaults.buttonColors()
            }
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Button(
                    onClick = { pendingAction = action },
                    modifier = Modifier.fillMaxWidth().semantics {
                        contentDescription = action.title
                        stateDescription = if (isActionRunning) "执行中不可点击" else "可点击"
                    },
                    enabled = !isActionRunning,
                    colors = colors,
                ) {
                    Text(action.title)
                }
                Text(
                    text = action.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    modifier = Modifier.padding(start = 2.dp),
                )
            }
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
                        if (action.isLongRunning) {
                            append("\n该动作可能耗时 1-2 分钟。")
                        }
                        if (action.isDanger) {
                            append("\n该动作可能会中断正在运行的服务。")
                        }
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
        shape = RoundedCornerShape(14.dp),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(card.title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(card.value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = TextPrimary)
            Text(card.subtitle, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
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
