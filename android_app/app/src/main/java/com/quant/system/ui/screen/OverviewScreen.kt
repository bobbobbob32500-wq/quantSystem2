package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.Metric
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

private data class TaskEntry(
    val id: String,
    val title: String,
    val subtitle: String,
    val onClick: () -> Unit,
)

private data class OverviewQuickCard(
    val id: String,
    val title: String,
    val value: String,
    val subtitle: String,
    val onClick: () -> Unit,
)

@Composable
fun OverviewScreen(
    snapshot: DashboardSnapshot?,
    isLoading: Boolean,
    isActionRunning: Boolean,
    message: String?,
    noticeType: NoticeType,
    autoRefreshSecondsRemaining: Int,
    lastSyncedAtLabel: String?,
    dataSourceLabel: String,
    networkStatusLabel: String,
    isUsingCachedData: Boolean,
    onRefresh: () -> Unit,
    onRunStockSelection: () -> Unit,
    onGeneratePlan: () -> Unit,
    onOpenActions: () -> Unit,
    onNavigateToCandidates: () -> Unit,
    onNavigateToTrades: () -> Unit,
) {
    val todayBoard = snapshot?.todayBoard
    val topSubtitle = remember(snapshot) {
        listOfNotNull(
            snapshot?.meta?.appName,
            snapshot?.meta?.generatedLabel,
            snapshot?.meta?.marketSession?.phase,
        ).joinToString(" · ").ifBlank { "移动决策台" }
    }
    val heroSubtitle = remember(isActionRunning, autoRefreshSecondsRemaining, lastSyncedAtLabel) {
        if (isActionRunning) {
            "动作执行中，自动刷新暂时停止"
        } else {
            "${autoRefreshSecondsRemaining}s 后刷新 · 最近同步 ${lastSyncedAtLabel ?: "--"}"
        }
    }
    val heroStats = remember(snapshot) {
        listOf(
            Triple("候选", "${snapshot?.candidatePool?.count ?: 0}", ""),
            Triple("信号", "${snapshot?.signals?.recentCount ?: 0}", ""),
            Triple("持仓", "${snapshot?.virtualTrades?.openCount ?: 0}", ""),
        )
    }
    val quickActions = remember(onRunStockSelection, onGeneratePlan, onOpenActions, onNavigateToCandidates) {
        listOf(
            QuickAction(icon = "选", label = "执行选股", onClick = onRunStockSelection),
            QuickAction(icon = "候", label = "候选池", onClick = onNavigateToCandidates),
            QuickAction(icon = "计", label = "生成计划", onClick = onGeneratePlan),
            QuickAction(icon = "动", label = "动作中心", onClick = onOpenActions),
        )
    }
    val taskEntries = remember(onRunStockSelection, onGeneratePlan, onNavigateToCandidates, onNavigateToTrades) {
        listOf(
            TaskEntry(
                id = "run_selection",
                title = "执行选股",
                subtitle = "快速触发选股，结果到候选池查看",
                onClick = onRunStockSelection,
            ),
            TaskEntry(
                id = "view_candidates",
                title = "查看候选池",
                subtitle = "进入候选池页面做策略筛选与标的查看",
                onClick = onNavigateToCandidates,
            ),
            TaskEntry(
                id = "generate_plan",
                title = "生成盘前计划",
                subtitle = "生成今日计划并同步到历史记录",
                onClick = onGeneratePlan,
            ),
            TaskEntry(
                id = "view_trades",
                title = "查看持仓",
                subtitle = "检查盈亏、提醒和卖出记录",
                onClick = onNavigateToTrades,
            ),
        )
    }
    val overviewCards = remember(snapshot, onNavigateToCandidates, onNavigateToTrades, onOpenActions, onRefresh) {
        val candidateCount = snapshot?.candidatePool?.count ?: snapshot?.candidatePool?.topCandidates?.size ?: 0
        val signalCount = snapshot?.signals?.recentCount ?: snapshot?.signals?.latestItems?.size ?: 0
        val openTrades = snapshot?.virtualTrades?.openCount ?: snapshot?.virtualTrades?.openTrades?.size ?: 0
        val healthLabel = snapshot?.health?.statusLabel ?: "未知"
        listOf(
            OverviewQuickCard(
                id = "candidate_count",
                title = "候选池",
                value = "$candidateCount",
                subtitle = "点击进入候选筛选",
                onClick = onNavigateToCandidates,
            ),
            OverviewQuickCard(
                id = "signal_count",
                title = "信号动态",
                value = "$signalCount",
                subtitle = "查看动作与信号状态",
                onClick = onOpenActions,
            ),
            OverviewQuickCard(
                id = "trade_count",
                title = "持仓数量",
                value = "$openTrades",
                subtitle = "点击进入持仓管理",
                onClick = onNavigateToTrades,
            ),
            OverviewQuickCard(
                id = "health_status",
                title = "系统健康",
                value = healthLabel,
                subtitle = "下拉可刷新状态",
                onClick = onRefresh,
            ),
        )
    }

    RefreshContainer(isRefreshing = isLoading, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier.padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item { TopBar(title = "首页", subtitle = topSubtitle) }

            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }

            if (isLoading && snapshot == null) {
                item { LoadingSkeletonCard(lines = 5) }
                items(4, contentType = { "skeleton" }) { LoadingSkeletonCard() }
                return@LazyColumn
            }

            item {
                HeroSection(
                    title = todayBoard?.action ?: snapshot?.meta?.marketSession?.detail ?: "市场状态",
                    value = todayBoard?.status ?: "系统运行中",
                    subtitle = heroSubtitle,
                    stats = heroStats,
                )
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatusPill(
                        text = "数据源：$dataSourceLabel",
                        tone = if (isUsingCachedData) PillTone.Neutral else PillTone.Positive,
                    )
                    StatusPill(
                        text = networkStatusLabel,
                        tone = when {
                            "正常" in networkStatusLabel -> PillTone.Positive
                            "较慢" in networkStatusLabel -> PillTone.Neutral
                            else -> PillTone.Negative
                        },
                    )
                }
            }

            item { QuickActions(actions = quickActions) }

            item { SectionHeader("快捷概览") }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OverviewQuickCardItem(card = overviewCards[0], modifier = Modifier.weight(1f))
                    OverviewQuickCardItem(card = overviewCards[1], modifier = Modifier.weight(1f))
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OverviewQuickCardItem(card = overviewCards[2], modifier = Modifier.weight(1f))
                    OverviewQuickCardItem(card = overviewCards[3], modifier = Modifier.weight(1f))
                }
            }

            if (todayBoard != null) {
                item { SectionHeader("今日决策") }
                todayBoard.reason?.takeIf { it.isNotBlank() }?.let { reason ->
                    item { DetailCard(title = "风险提示", lines = listOf(reason)) }
                }
                if (todayBoard.cards.isNotEmpty()) {
                    items(todayBoard.cards, key = { "${it.label}_${it.value}" }) { card ->
                        ValueCard(
                            title = card.label ?: "--",
                            value = card.value ?: "--",
                            detail = card.note ?: "",
                        )
                    }
                }
                if (todayBoard.highlights.isNotEmpty()) {
                    item { DetailCard(title = "待办任务", lines = todayBoard.highlights.take(6)) }
                }
            }

            item { SectionHeader("任务中心") }
            items(taskEntries, key = { it.id }, contentType = { "task" }) { task ->
                TaskEntryCard(title = task.title, subtitle = task.subtitle, onClick = task.onClick)
            }

            item {
                HealthCard(
                    status = snapshot?.health?.statusLabel ?: "未知",
                    subtitle = snapshot?.health?.subtitle ?: "暂无健康快照",
                    isHealthy = snapshot?.health?.status == "healthy",
                )
            }

            val metrics = snapshot?.overview?.metrics.orEmpty()
            if (metrics.isNotEmpty()) {
                item { SectionHeader("核心指标") }
                items(
                    items = metrics,
                    key = { it.key ?: it.label ?: it.hashCode().toString() },
                    contentType = { "metric" },
                ) { metric ->
                    MetricCard(metric)
                }
            }
        }
    }
}

@Composable
private fun TaskEntryCard(
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Card(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "$title。$subtitle" },
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Surface),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, color = TextPrimary)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

@Composable
private fun OverviewQuickCardItem(
    card: OverviewQuickCard,
    modifier: Modifier = Modifier,
) {
    Card(
        onClick = card.onClick,
        modifier = modifier.semantics { contentDescription = "${card.title}：${card.value}，${card.subtitle}" },
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Surface),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = card.title,
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary,
            )
            Text(
                text = card.value,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = TextPrimary,
            )
            Text(
                text = card.subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
        }
    }
}

@Composable
private fun MetricCard(metric: Metric) {
    ValueCard(
        title = metric.label ?: metric.key ?: "--",
        value = formatMetricValue(metric.value, metric.unit),
        detail = metric.note ?: "",
    )
}

private fun formatMetricValue(value: JsonElement?, unit: String?): String {
    if (value == null) return "--"
    val rendered = if (value is JsonPrimitive && value.isString) value.content else value.toString()
    return listOf(rendered, unit.orEmpty()).filter { it.isNotBlank() }.joinToString(" ")
}
