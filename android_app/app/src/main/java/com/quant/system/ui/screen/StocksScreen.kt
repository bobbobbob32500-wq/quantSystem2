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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.StockSelectionHistoryRecord
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private enum class StockSelectionStrategy(val key: String, val label: String) {
    Secondary("secondary_launch", "二次启动"),
    Legacy("legacy", "原策略"),
    Breakout("breakout", "突破策略"),
    Both("both", "融合策略"),
}

@Composable
fun StocksScreen(
    snapshot: DashboardSnapshot?,
    selectionHistory: List<StockSelectionHistoryRecord>,
    preferredStrategyKey: String?,
    selectedHistoryId: Long?,
    historyFilterStrategy: String,
    monitorExpectedActive: Boolean,
    isActionRunning: Boolean,
    runningAction: String?,
    actionElapsedSeconds: Int,
    selectionStatusLabel: String,
    selectionLastStrategyLabel: String,
    selectionLastUpdatedAtLabel: String,
    selectionLastCount: Int?,
    isRefreshing: Boolean,
    message: String?,
    noticeType: NoticeType,
    onRefresh: () -> Unit,
    onRunStockSelection: (String) -> Unit,
    onPushSelection: () -> Unit,
    onApplySelectionHistory: (Long) -> Unit,
    onChangeHistoryFilterStrategy: (String) -> Unit,
    onDeleteSelectionHistory: (Long) -> Unit,
    onClearSelectionHistory: () -> Unit,
    onOpenStockDetail: (String) -> Unit,
    onOpenStrategyCenter: () -> Unit,
) {
    val candidates = snapshot?.candidatePool?.topCandidates.orEmpty()
    val freshnessLabel = snapshot?.candidatePool?.freshnessLabel?.takeIf { it.isNotBlank() } ?: "待更新"
    val candidateCount = snapshot?.candidatePool?.count ?: candidates.size
    val monitorSession = snapshot?.monitorSession
    val monitorStatus = when {
        monitorSession?.runtimeUsable == true -> "监控正常运行"
        isActionRunning && runningAction == "start_monitor_runtime" -> "监控启动中..."
        monitorExpectedActive -> "监控已开启（等待状态回传）"
        monitorSession?.isActive == true -> "监控已开启（数据链路待就绪）"
        else -> "监控未开启"
    }
    var selectedStrategy by rememberSaveable {
        mutableStateOf(preferredStrategyKey ?: StockSelectionStrategy.Secondary.key)
    }
    val strategies = remember { StockSelectionStrategy.entries.map { it.key to it.label } }
    val historyStrategies = remember {
        listOf("all" to "全部历史") + StockSelectionStrategy.entries.map { it.key to it.label }
    }

    LaunchedEffect(preferredStrategyKey) {
        preferredStrategyKey?.takeIf { it.isNotBlank() }?.let { selectedStrategy = it }
    }

    RefreshContainer(isRefreshing = isRefreshing, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                TopBar(
                    title = "候选池",
                    subtitle = buildString {
                        append("数量：$candidateCount")
                        snapshot?.candidatePool?.avgScore?.let { append(" · 平均分 ${"%.2f".format(it)}") }
                    },
                )
            }
            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }
            if (isRefreshing && candidates.isEmpty()) {
                items(5) { LoadingSkeletonCard() }
                return@LazyColumn
            }

            item {
                StrategyTabs(
                    strategies = strategies,
                    selectedStrategy = selectedStrategy,
                    onStrategySelected = { selectedStrategy = it },
                )
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    PrimaryButton(
                        text = "执行选股",
                        onClick = { onRunStockSelection(selectedStrategy) },
                        modifier = Modifier.weight(1f),
                    )
                    SecondaryButton(
                        text = "推送候选",
                        onClick = onPushSelection,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
            item {
                SecondaryButton(
                    text = "策略说明与参数",
                    onClick = onOpenStrategyCenter,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                DetailCard(
                    title = "选股状态",
                    lines = listOf(
                        "监控状态：$monitorStatus",
                        "监控详情：${monitorSession?.runtimeStatusLabel ?: monitorSession?.statusLabel ?: "--"}",
                        "监控最近刷新：${monitorSession?.lastRefreshAt ?: "--"}",
                        "结果：$selectionStatusLabel",
                        if (isActionRunning && runningAction == "run_stock_selection") {
                            "执行进度：进行中（${actionElapsedSeconds}s）"
                        } else {
                            "执行进度：空闲"
                        },
                        "最近策略：$selectionLastStrategyLabel",
                        "最近结果数量：${selectionLastCount ?: "--"}",
                        "最近结果时间：$selectionLastUpdatedAtLabel",
                        "当前策略：${strategyLabel(selectedStrategy)}",
                        "候选数量：$candidateCount",
                        "最近更新：$freshnessLabel",
                    ),
                )
            }

            if (candidates.isEmpty()) {
                item { EmptyStateCard("当前没有候选标的，请先执行选股。") }
            } else {
                items(
                    items = candidates,
                    key = { it.symbol ?: it.name ?: it.hashCode().toString() },
                    contentType = { "candidate" },
                ) { candidate ->
                    CandidateCard(
                        candidate = candidate,
                        onClick = { onOpenStockDetail(candidate.symbol ?: "") },
                    )
                }
            }

            if (selectionHistory.isNotEmpty()) {
                item {
                    SectionHeader(
                        title = "历史选股记录",
                        action = {
                            TextButton(onClick = onClearSelectionHistory) {
                                Text("清空全部")
                            }
                        },
                    )
                }
                item {
                    StrategyTabs(
                        strategies = historyStrategies,
                        selectedStrategy = historyFilterStrategy,
                        onStrategySelected = onChangeHistoryFilterStrategy,
                    )
                }
                items(
                    items = selectionHistory.take(10),
                    key = { it.id },
                    contentType = { "selection_history" },
                ) { history ->
                    SelectionHistoryCard(
                        record = history,
                        selected = selectedHistoryId == history.id,
                        onRestore = { onApplySelectionHistory(history.id) },
                        onDelete = { onDeleteSelectionHistory(history.id) },
                    )
                }
            }

            item { androidx.compose.foundation.layout.Spacer(modifier = Modifier.padding(bottom = 16.dp)) }
        }
    }
}

@Composable
private fun CandidateCard(candidate: Candidate, onClick: () -> Unit) {
    val score = candidate.score ?: 0.0
    val changePct = candidate.pctChg ?: candidate.quotePctChange
    val currentPrice = candidate.currentPrice ?: candidate.lastPrice ?: candidate.close
    val tone = when {
        score >= 85 -> PillTone.Positive
        score >= 70 -> PillTone.Neutral
        else -> PillTone.Negative
    }
    val strategyTag = strategyLabel(candidate.strategyProfile)

    Card(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "${candidate.name ?: "--"}，代码 ${candidate.symbol ?: "--"}，评分 ${"%.2f".format(score)}"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = candidate.name ?: "--",
                        style = MaterialTheme.typography.titleSmall,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = candidate.symbol ?: "--",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(text = "评分 ${"%.2f".format(score)}", tone = tone)
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusPill(text = strategyTag, tone = PillTone.Neutral)
                run {
                    val pctTone = when {
                        changePct == null -> PillTone.Neutral
                        changePct > 0 -> PillTone.Positive
                        changePct < 0 -> PillTone.Negative
                        else -> PillTone.Neutral
                    }
                    val pctText = if (changePct == null) "--" else "${if (changePct > 0) "+" else ""}${"%.2f".format(changePct)}%"
                    StatusPill(text = "当日 $pctText", tone = pctTone)
                }
            }

            ScoreBar(progress = (score / 100.0).coerceIn(0.0, 1.0).toFloat(), tone = tone)

            val detailMetrics = buildList {
                currentPrice?.let { add("现价 ${"%.2f".format(it)}") }
                candidate.triggerPrice?.let { add("触发价 ${"%.2f".format(it)}") }
                candidate.entryPrice?.let { add("买入触发价 ${"%.2f".format(it)}") }
                candidate.stopLoss?.let { add("止损参考 ${"%.2f".format(it)}") }
                candidate.volRatio5?.let { add("量比 ${"%.2f".format(it)}x") }
            }
            if (detailMetrics.isNotEmpty()) {
                Text(
                    text = detailMetrics.joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }

            candidate.triggerReason?.takeIf { it.isNotBlank() }?.let { reason ->
                Text(
                    text = "入选原因：$reason",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            Text(
                text = "点击查看个股详情与风险提示。",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
        }
    }
}

private fun strategyLabel(raw: String?): String {
    return when (raw?.trim()?.lowercase()) {
        "secondary_launch" -> "二次启动"
        "legacy" -> "原策略"
        "breakout" -> "突破策略"
        "both" -> "融合策略"
        null, "" -> "未标注策略"
        else -> raw
    }
}

@Composable
private fun SelectionHistoryCard(
    record: StockSelectionHistoryRecord,
    selected: Boolean,
    onRestore: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(
        onClick = onRestore,
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "策略 ${record.strategyLabel}，候选 ${record.candidateCount}，时间 ${record.createdAtLabel}"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusPill(text = record.strategyLabel, tone = PillTone.Neutral)
                StatusPill(text = "候选 ${record.candidateCount}", tone = PillTone.Positive)
                if (selected) {
                    StatusPill(text = "当前已恢复", tone = PillTone.Positive)
                }
            }
            Text(
                text = "执行时间：${record.createdAtLabel}",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            if (record.topSymbols.isNotEmpty()) {
                Text(
                    text = "标的：${record.topSymbols.joinToString(" · ")}",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            Text(
                text = "点击恢复此批候选结果",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onDelete) {
                    Text("删除该记录")
                }
            }
        }
    }
}
