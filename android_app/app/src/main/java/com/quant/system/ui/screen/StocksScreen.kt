package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.StockSelectionHistoryRecord
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import kotlinx.coroutines.flow.distinctUntilChanged

private enum class StockSelectionStrategy(val key: String, val label: String) {
    Secondary("secondary_launch", "二次启动"),
    Breakout("breakout", "突破策略"),
    WideBreakout("wide_breakout", "宽进突破"),
    Alpha158("alpha158", "Alpha158"),
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
    selectionStatusLabel: String,
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
    onOpenStrategyCenter: () -> Unit,
) {
    val listState = rememberLazyListState()
    val allCandidates = snapshot?.candidatePool?.topCandidates.orEmpty()
    val freshnessLabel = snapshot?.candidatePool?.freshnessLabel?.takeIf { it.isNotBlank() } ?: "待更新"
    val poolGeneratedLabel = snapshot?.candidatePool?.createdTime?.takeIf { it.isNotBlank() }
        ?: snapshot?.meta?.generatedLabel?.takeIf { it.isNotBlank() }
        ?: freshnessLabel.removePrefix("缓存生成于 ").ifBlank { "待更新" }
    val totalCandidateCount = snapshot?.candidatePool?.count ?: allCandidates.size
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
    val candidates = remember(allCandidates, selectedStrategy) {
        allCandidates.filter { candidateMatchesStrategy(it, selectedStrategy) }
    }
    var visibleCandidateCount by rememberSaveable(selectedStrategy, candidates.size) {
        mutableIntStateOf(minOf(CANDIDATE_PAGE_SIZE, candidates.size))
    }
    val displayCandidates by remember(candidates, visibleCandidateCount) {
        androidx.compose.runtime.derivedStateOf { candidates.take(visibleCandidateCount) }
    }
    val candidateCount = candidates.size
    val avgScore = remember(candidates) {
        candidates.mapNotNull { it.score }.takeIf { it.isNotEmpty() }?.average()
    }

    LaunchedEffect(preferredStrategyKey) {
        preferredStrategyKey?.takeIf { it.isNotBlank() }?.let { selectedStrategy = it }
    }

    LaunchedEffect(selectedStrategy, candidates.size) {
        visibleCandidateCount = minOf(CANDIDATE_PAGE_SIZE, candidates.size)
    }

    LaunchedEffect(listState, candidates.size, visibleCandidateCount) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1 }
            .distinctUntilChanged()
            .collect { lastVisible ->
                if (lastVisible >= displayCandidates.lastIndex - CANDIDATE_PREFETCH_THRESHOLD &&
                    visibleCandidateCount < candidates.size
                ) {
                    visibleCandidateCount = minOf(
                        visibleCandidateCount + CANDIDATE_PAGE_SIZE,
                        candidates.size,
                    )
                }
            }
    }

    RefreshContainer(isRefreshing = isRefreshing, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 20.dp),
            state = listState,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
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
                CandidateCommandCard(
                    strategyLabel = strategyLabel(selectedStrategy),
                    candidateCount = candidateCount,
                    totalCandidateCount = totalCandidateCount,
                    avgScore = avgScore,
                    freshnessLabel = freshnessLabel,
                    monitorStatus = monitorStatus,
                    selectionStatusLabel = selectionStatusLabel,
                    isActionRunning = isActionRunning,
                    runningAction = runningAction,
                    onRunStockSelection = { onRunStockSelection(selectedStrategy) },
                    onPushSelection = onPushSelection,
                    onOpenStrategyCenter = onOpenStrategyCenter,
                )
            }

            if (candidates.isEmpty()) {
                item { EmptyStateCard("当前策略下暂无候选标的，请切换策略或先执行选股。") }
            } else {
                itemsIndexed(
                    items = displayCandidates,
                    key = { index, candidate -> buildCandidateStableKey(candidate, selectedStrategy, index) },
                    contentType = { _, _ -> "candidate" },
                ) { _, candidate ->
                    CandidateCard(
                        candidate = candidate,
                        generatedAtLabel = candidateGeneratedAtLabel(candidate, poolGeneratedLabel),
                        dataDateLabel = candidateDataDateLabel(candidate),
                        buyAtLabel = candidateRecommendedBuyLabel(candidate, poolGeneratedLabel),
                    )
                }
                if (displayCandidates.size < candidates.size) {
                    item(key = "candidate_load_more_hint") {
                        DetailCard(
                            title = "正在加载更多候选",
                            lines = listOf("已显示 ${displayCandidates.size}/${candidates.size}"),
                        )
                    }
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

private const val CANDIDATE_PAGE_SIZE = 24
private const val CANDIDATE_PREFETCH_THRESHOLD = 6

@Composable
private fun CandidateCard(
    candidate: Candidate,
    generatedAtLabel: String,
    dataDateLabel: String,
    buyAtLabel: String,
) {
    val displaySymbol = candidate.symbol?.trim()?.takeIf { it.isNotBlank() }
        ?: candidate.tsCode?.substringBefore(".")?.trim()?.takeIf { it.isNotBlank() }
    val score = candidate.score ?: 0.0
    val quoteLabel = candidateQuoteLabel(candidate)
    val changePct = quoteLabel.changePct
    val currentPrice = candidate.currentPrice ?: candidate.lastPrice ?: candidate.close
    val tone = when {
        score >= 85 -> PillTone.Positive
        score >= 70 -> PillTone.Neutral
        else -> PillTone.Negative
    }
    val strategyTag = strategyLabel(candidate.strategyProfile ?: candidate.strategyName)

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "${candidate.name ?: "--"}，代码 ${displaySymbol ?: "--"}，评分 ${"%.2f".format(score)}"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(22.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .background(Primary.copy(alpha = 0.1f), RoundedCornerShape(14.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = displaySymbol?.takeLast(2) ?: "股",
                        color = Primary,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
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
                        text = displaySymbol ?: "--",
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
                    StatusPill(text = "${quoteLabel.changeLabel} $pctText", tone = pctTone)
                }
            }

            ScoreBar(progress = (score / 100.0).coerceIn(0.0, 1.0).toFloat(), tone = tone)

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CandidateMetricChip(
                    label = quoteLabel.priceLabel,
                    value = currentPrice?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
                CandidateMetricChip(
                    label = "触发价",
                    value = candidate.triggerPrice?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
                CandidateMetricChip(
                    label = "止损",
                    value = candidate.stopLoss?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
            }

            candidate.triggerReason?.takeIf { it.isNotBlank() }?.let { reason ->
                Text(
                    text = "入选原因：$reason",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
                shape = RoundedCornerShape(18.dp),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    CandidateMetaLine(label = "数据基准日", value = dataDateLabel)
                    CandidateMetaLine(label = "候选生成时间", value = generatedAtLabel)
                    CandidateMetaLine(label = "计划买入窗口", value = buyAtLabel)
                    CandidateMetaLine(label = "行情口径", value = quoteLabel.sourceLabel)
                }
            }
        }
    }
}

@Composable
private fun CandidateMetaLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            color = TextPrimary,
            fontWeight = FontWeight.Medium,
        )
    }
}

private fun candidateGeneratedAtLabel(candidate: Candidate, fallback: String): String {
    return candidate.createdTime?.takeIf { it.isNotBlank() }
        ?: fallback
}

private fun candidateDataDateLabel(candidate: Candidate): String {
    return candidate.quoteTradeDate?.let(::formatDateLabel)
        ?: candidate.tradeDate?.let(::formatDateLabel)
        ?: "--"
}

private fun candidateRecommendedBuyLabel(candidate: Candidate, poolGeneratedLabel: String): String {
    return candidate.buyTimeLabel?.takeIf { it.isNotBlank() }
        ?: candidate.buyTime?.takeIf { it.isNotBlank() }
        ?: candidate.entryTime?.takeIf { it.isNotBlank() }
        ?: candidate.triggerTime?.takeIf { it.isNotBlank() }
        ?: candidate.nextTradeDate?.let { "${formatDateLabel(it)} 盘中触发" }
        ?: extractDateLabel(candidate.createdTime)?.let { "$it 盘中触发" }
        ?: extractDateLabel(poolGeneratedLabel)?.let { "$it 盘中触发" }
        ?: candidate.tradeDate?.let { "${formatDateLabel(it)} 后一交易日盘中触发" }
        ?: "待盘中触发"
}

private data class CandidateQuoteLabel(
    val priceLabel: String,
    val changeLabel: String,
    val sourceLabel: String,
    val changePct: Double?,
)

private fun candidateQuoteLabel(candidate: Candidate): CandidateQuoteLabel {
    val quoteTime = candidate.quoteTime?.takeIf { it.isNotBlank() }
    val quoteTradeDate = candidate.quoteTradeDate?.takeIf { it.isNotBlank() }?.let(::formatDateLabel)
    val quoteSource = candidate.quoteSource?.takeIf { it.isNotBlank() }
    val isRealtimeQuote = candidate.quoteIsRealtime == true ||
        (quoteTime != null && quoteSource?.contains("实时") == true)
    return if (isRealtimeQuote) {
        CandidateQuoteLabel(
            priceLabel = "最新价",
            changeLabel = "实时",
            sourceLabel = listOfNotNull(
                quoteTradeDate?.let { "日期 $it" },
                quoteTime?.let { "时间 $it" },
                quoteSource?.let { "来源 $it" },
            ).joinToString(" · ").ifBlank { "实时行情" },
            changePct = candidate.quotePctChange ?: candidate.pctChg,
        )
    } else if (quoteTradeDate != null || quoteSource != null) {
        CandidateQuoteLabel(
            priceLabel = "最新日线价",
            changeLabel = "基准日",
            sourceLabel = listOfNotNull(
                quoteTradeDate?.let { "日期 $it" },
                quoteSource?.let { "来源 $it" },
            ).joinToString(" · ").ifBlank { "最新日线，非实时行情" },
            changePct = candidate.pctChg ?: candidate.quotePctChange,
        )
    } else {
        CandidateQuoteLabel(
            priceLabel = "候选快照价",
            changeLabel = "基准日",
            sourceLabel = "候选池快照，非实时行情",
            changePct = candidate.pctChg ?: candidate.quotePctChange,
        )
    }
}

private fun extractDateLabel(raw: String?): String? {
    val value = raw?.trim()?.takeIf { it.isNotBlank() } ?: return null
    Regex("""\d{4}-\d{2}-\d{2}""").find(value)?.let { return it.value }
    Regex("""\d{8}""").find(value)?.let { return formatDateLabel(it.value) }
    return null
}

private fun formatDateLabel(raw: String): String {
    val value = raw.trim()
    return when {
        value.length == 8 && value.all(Char::isDigit) -> "${value.substring(0, 4)}-${value.substring(4, 6)}-${value.substring(6, 8)}"
        else -> value
    }
}

@Composable
private fun CandidateCommandCard(
    strategyLabel: String,
    candidateCount: Int,
    totalCandidateCount: Int,
    avgScore: Double?,
    freshnessLabel: String,
    monitorStatus: String,
    selectionStatusLabel: String,
    isActionRunning: Boolean,
    runningAction: String?,
    onRunStockSelection: () -> Unit,
    onPushSelection: () -> Unit,
    onOpenStrategyCenter: () -> Unit,
) {
    val runSelectionLoading = isActionRunning && runningAction == "run_stock_selection"
    val pushSelectionLoading = isActionRunning && runningAction == "push_selection_wecom"
    val commandBusy = isActionRunning

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = strategyLabel,
                        style = MaterialTheme.typography.titleLarge,
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = "当前策略候选与动作出口",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(text = freshnessLabel, tone = PillTone.Neutral)
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CandidateMetricChip(
                    label = "候选",
                    value = "$candidateCount / $totalCandidateCount",
                    modifier = Modifier.weight(1f),
                )
                CandidateMetricChip(
                    label = "平均分",
                    value = avgScore?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
                CandidateMetricChip(
                    label = "状态",
                    value = selectionStatusLabel,
                    modifier = Modifier.weight(1f),
                )
            }

            DetailCard(
                title = "当前链路",
                lines = listOf(
                    "监控：$monitorStatus",
                    "推送：执行选股后可将当前策略重点候选直接推送到消息流。",
                ),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                PrimaryButton(
                    text = if (runSelectionLoading) "执行中..." else "执行选股",
                    onClick = onRunStockSelection,
                    modifier = Modifier.weight(1f),
                    enabled = !commandBusy,
                )
                SecondaryButton(
                    text = if (pushSelectionLoading) "推送中..." else "推送候选",
                    onClick = onPushSelection,
                    modifier = Modifier.weight(1f),
                    enabled = !commandBusy,
                )
            }

            SecondaryButton(
                text = "策略说明与参数",
                onClick = onOpenStrategyCenter,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun CandidateMetricChip(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.6f)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = TextSecondary,
            )
            Text(
                text = value,
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

private fun strategyLabel(raw: String?): String {
    val key = normalizedStrategyKey(raw) ?: return "未标注策略"
    return when (key) {
        "secondary_launch" -> "二次启动"
        "breakout" -> "突破策略"
        "wide_breakout" -> "宽进突破"
        "alpha158" -> "Alpha158"
        "legacy" -> "原策略"
        "both" -> "融合策略"
        else -> raw?.trim().orEmpty().ifBlank { "未标注策略" }
    }
}

private fun normalizedStrategyKey(raw: String?): String? {
    val normalized = raw
        ?.trim()
        ?.takeIf { it.isNotBlank() && it != "?" && it != "--" }
        ?.lowercase()
        ?: return null
    return when {
        normalized.contains("secondary_launch") || normalized.contains("secondary") -> "secondary_launch"
        normalized.contains("wide_breakout") || normalized.contains("宽进突破") -> "wide_breakout"
        normalized.contains("alpha158") || normalized.contains("strong_start") || normalized == "alpha" -> "alpha158"
        normalized.contains("breakout") || normalized.contains("突破") -> "breakout"
        normalized == "legacy" -> "legacy"
        normalized == "both" -> "both"
        else -> normalized
    }
}

private fun candidateMatchesStrategy(candidate: Candidate, strategyKey: String): Boolean {
    val keys = listOfNotNull(
        normalizedStrategyKey(candidate.strategyProfile),
        normalizedStrategyKey(candidate.strategyName),
    )
    return keys.any { it == strategyKey }
}

private fun buildCandidateStableKey(candidate: Candidate, strategyKey: String, index: Int): String {
    val symbol = candidateDetailSymbol(candidate) ?: "unknown"
    val profile = normalizedStrategyKey(candidate.strategyProfile).orEmpty()
    val strategy = normalizedStrategyKey(candidate.strategyName).orEmpty()
    return "$strategyKey|$symbol|$profile|$strategy|$index"
}

private fun candidateDetailSymbol(candidate: Candidate): String? {
    return candidate.symbol?.trim()?.takeIf { it.isNotBlank() }
        ?: candidate.tsCode?.substringBefore(".")?.trim()?.takeIf { it.isNotBlank() }
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
