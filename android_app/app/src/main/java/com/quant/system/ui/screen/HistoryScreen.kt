package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.ActionRecord
import com.quant.system.data.model.BackgroundTaskRecord
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class HistoryOverviewCard(
    val id: String,
    val title: String,
    val value: String,
    val subtitle: String,
)

@Composable
fun HistoryScreen(
    records: List<ActionRecord>,
    backgroundTasks: List<BackgroundTaskRecord>,
    isRefreshing: Boolean,
    message: String?,
    noticeType: NoticeType,
    onRefresh: () -> Unit,
    onRetryTask: (String) -> Unit,
) {
    val runningCount = remember(backgroundTasks) {
        backgroundTasks.count { it.status.equals("queued", true) || it.status.equals("running", true) }
    }
    val failedCount = remember(backgroundTasks) {
        backgroundTasks.count { it.status.equals("failed", true) || it.status.equals("error", true) }
    }
    val overviewCards = remember(backgroundTasks, records, runningCount, failedCount) {
        listOf(
            HistoryOverviewCard(
                id = "tasks",
                title = "后台任务",
                value = "${backgroundTasks.size}",
                subtitle = "运行中 $runningCount",
            ),
            HistoryOverviewCard(
                id = "failed",
                title = "失败任务",
                value = "$failedCount",
                subtitle = "可重试任务重点关注",
            ),
            HistoryOverviewCard(
                id = "records",
                title = "执行记录",
                value = "${records.size}",
                subtitle = "最近动作历史",
            ),
        )
    }

    RefreshContainer(isRefreshing = isRefreshing, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                ScreenHeader(
                    title = "执行历史",
                    subtitle = "查看后台任务进度与动作执行记录",
                )
            }
            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    overviewCards.forEach { card ->
                        HistoryOverviewCardItem(
                            card = card,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }

            item {
                Button(
                    onClick = onRefresh,
                    modifier = Modifier.fillMaxWidth().semantics { contentDescription = "刷新历史" },
                    enabled = !isRefreshing,
                ) {
                    Text(if (isRefreshing) "刷新中..." else "刷新历史")
                }
            }

            if (backgroundTasks.isNotEmpty()) {
                item { SectionHeader("后台任务状态") }
                items(backgroundTasks.take(10), key = { it.taskId }) { task ->
                    BackgroundTaskCard(task = task, onRetryTask = onRetryTask)
                }
            }

            item { SectionHeader("动作执行记录") }
            if (isRefreshing && records.isEmpty()) {
                items(5) { LoadingSkeletonCard() }
                return@LazyColumn
            }
            if (records.isEmpty()) {
                item { EmptyStateCard("暂无动作执行记录，请先执行一次动作。") }
            } else {
                items(records, key = { "${it.actionKey}_${it.createdTime}" }) { record ->
                    ActionRecordCard(record = record)
                }
            }
        }
    }
}

@Composable
private fun HistoryOverviewCardItem(
    card: HistoryOverviewCard,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = Surface),
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

@Composable
private fun BackgroundTaskCard(
    task: BackgroundTaskRecord,
    onRetryTask: (String) -> Unit,
) {
    val status = task.status.orEmpty()
    Card(
        modifier = Modifier.fillMaxWidth().semantics {
            contentDescription = "${task.actionLabel ?: task.actionKey ?: task.taskId}，${statusLabel(status)}"
        },
        colors = CardDefaults.cardColors(containerColor = Surface),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = task.actionLabel ?: actionLabel(task.actionKey.orEmpty()),
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "进度：${task.progressPct ?: 0}%  开始：${task.startedAt ?: "--"}",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(text = statusLabel(status), tone = statusTone(status))
            }
            task.message?.takeIf { it.isNotBlank() }?.let { detail ->
                Text(text = detail, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
            }
            if (!task.errorCode.isNullOrBlank()) {
                Text(text = "错误码：${task.errorCode}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
            }
            if (task.retryable) {
                OutlinedButton(
                    onClick = { onRetryTask(task.taskId) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("重试任务")
                }
            }
        }
    }
}

@Composable
private fun ActionRecordCard(record: ActionRecord) {
    Card(
        modifier = Modifier.fillMaxWidth().semantics {
            contentDescription = "${actionLabel(record.actionKey)}，${statusLabel(record.status)}，${record.createdTime}"
        },
        colors = CardDefaults.cardColors(containerColor = Surface),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = actionLabel(record.actionKey),
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = record.createdTime,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(text = statusLabel(record.status), tone = statusTone(record.status))
            }
            record.message?.takeIf { it.isNotBlank() }?.let { detail ->
                Text(text = detail, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
            }
        }
    }
}

private fun statusTone(status: String): PillTone {
    return when {
        status.equals("success", ignoreCase = true) -> PillTone.Positive
        status.equals("error", ignoreCase = true) -> PillTone.Negative
        status.equals("failed", ignoreCase = true) -> PillTone.Negative
        status.equals("running", ignoreCase = true) -> PillTone.Neutral
        status.equals("queued", ignoreCase = true) -> PillTone.Neutral
        else -> PillTone.Neutral
    }
}

private fun statusLabel(status: String): String {
    return when {
        status.equals("success", ignoreCase = true) -> "成功"
        status.equals("error", ignoreCase = true) -> "错误"
        status.equals("failed", ignoreCase = true) -> "失败"
        status.equals("running", ignoreCase = true) -> "执行中"
        status.equals("queued", ignoreCase = true) -> "排队中"
        else -> status.ifBlank { "未知" }
    }
}

private fun actionLabel(actionKey: String): String {
    return when (actionKey) {
        "generate_plan" -> "生成计划"
        "run_stock_selection" -> "执行选股"
        "start_monitor_runtime" -> "启动监控运行时"
        "stop_monitor_runtime" -> "停止监控运行时"
        "generate_post_market_review" -> "生成收盘复盘"
        "push_selection_wecom" -> "推送候选池"
        else -> actionKey
    }
}
