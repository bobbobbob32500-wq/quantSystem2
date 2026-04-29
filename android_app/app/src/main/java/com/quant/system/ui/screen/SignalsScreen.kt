package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.SignalItem
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import kotlinx.coroutines.flow.distinctUntilChanged

private data class SignalSummary(
    val title: String,
    val value: String,
    val detail: String,
)

@Composable
fun SignalsScreen(
    snapshot: DashboardSnapshot?,
    isRefreshing: Boolean,
    message: String?,
    noticeType: NoticeType,
    onRefresh: () -> Unit,
    onOpenStockDetail: (String) -> Unit,
) {
    val signals = snapshot?.signals?.latestItems.orEmpty()
    val listState = rememberLazyListState()
    var query by rememberSaveable { mutableStateOf("") }
    var selectedType by rememberSaveable { mutableStateOf("全部") }
    var visibleSignalCount by rememberSaveable { mutableIntStateOf(SIGNAL_PAGE_SIZE) }

    val normalizedQuery by remember(query) { derivedStateOf { query.trim().lowercase() } }
    val searchableSignals by remember(signals) {
        derivedStateOf {
            signals.map { signal ->
                signal to listOf(
                    signal.name.orEmpty(),
                    signal.tsCode.orEmpty(),
                    signal.signalType.orEmpty(),
                    signal.triggerReason.orEmpty(),
                    signal.suggestion.orEmpty(),
                ).joinToString(" ").lowercase()
            }
        }
    }
    val signalTypes by remember(signals) {
        derivedStateOf {
            listOf("全部") + signals
                .mapNotNull { it.signalType?.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .sorted()
        }
    }
    val filteredSignals by remember(searchableSignals, normalizedQuery, selectedType) {
        derivedStateOf {
            searchableSignals.mapNotNull { (signal, normalizedText) ->
                val matchQuery = normalizedQuery.isBlank() || normalizedQuery in normalizedText
                val matchType = selectedType == "全部" || signal.signalType == selectedType
                if (matchQuery && matchType) signal else null
            }
        }
    }
    val displaySignals by remember(filteredSignals, visibleSignalCount) {
        derivedStateOf { filteredSignals.take(visibleSignalCount) }
    }

    LaunchedEffect(selectedType, normalizedQuery, filteredSignals.size) {
        visibleSignalCount = minOf(SIGNAL_PAGE_SIZE, filteredSignals.size)
    }

    LaunchedEffect(listState, filteredSignals.size, visibleSignalCount) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1 }
            .distinctUntilChanged()
            .collect { lastVisible ->
                if (lastVisible >= displaySignals.lastIndex - SIGNAL_PREFETCH_THRESHOLD &&
                    visibleSignalCount < filteredSignals.size
                ) {
                    visibleSignalCount = minOf(
                        visibleSignalCount + SIGNAL_PAGE_SIZE,
                        filteredSignals.size,
                    )
                }
            }
    }
    val positiveCount = remember(signals) { signals.count { signalTone(it.signalType) == PillTone.Positive } }
    val negativeCount = remember(signals) { signals.count { signalTone(it.signalType) == PillTone.Negative } }
    val signalSummaries = remember(signals, positiveCount, negativeCount, signalTypes) {
        listOf(
            SignalSummary("最近信号", signals.size.toString(), "当前批次总量"),
            SignalSummary("偏多", positiveCount.toString(), "买入 / 看多"),
            SignalSummary("偏空", negativeCount.toString(), "卖出 / 减仓"),
            SignalSummary("类型", (signalTypes.size - 1).coerceAtLeast(0).toString(), "筛选维度"),
        )
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
            if (isRefreshing && signals.isEmpty()) {
                items(5) { LoadingSkeletonCard() }
                return@LazyColumn
            }

            item {
                HeroSection(
                    title = "信号流",
                    value = "${signals.size}",
                    subtitle = snapshot?.signals?.latestSignalLabel ?: "先看高优先级，再看普通信号。",
                    stats = listOf(
                        Triple("偏多", positiveCount.toString(), ""),
                        Triple("偏空", negativeCount.toString(), ""),
                        Triple("筛选后", filteredSignals.size.toString(), ""),
                    ),
                )
            }

            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Surface),
                    shape = RoundedCornerShape(24.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
                ) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text(
                            text = "筛选条件",
                            style = MaterialTheme.typography.titleMedium,
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                        )
                        OutlinedTextField(
                            value = query,
                            onValueChange = { query = it },
                            modifier = Modifier
                                .fillMaxWidth()
                                .semantics { contentDescription = "搜索信号" },
                            singleLine = true,
                            label = { Text("搜索名称 / 代码 / 类型 / 原因") },
                            shape = RoundedCornerShape(18.dp),
                        )
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(signalTypes) { type ->
                                FilterChip(
                                    selected = type == selectedType,
                                    onClick = { selectedType = type },
                                    label = { Text(type) },
                                    modifier = Modifier.semantics { contentDescription = "信号类型 $type" },
                                )
                            }
                        }
                    }
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    signalSummaries.take(2).forEach { summary ->
                        SignalSummaryCard(summary = summary, modifier = Modifier.weight(1f))
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    signalSummaries.drop(2).forEach { summary ->
                        SignalSummaryCard(summary = summary, modifier = Modifier.weight(1f))
                    }
                }
            }

            item { SectionHeader("信号时间线") }
            if (filteredSignals.isEmpty()) {
                item { EmptyStateCard("当前筛选条件下没有匹配信号，请调整关键词或类型。") }
            } else {
                itemsIndexed(
                    items = displaySignals,
                    key = { index, signal ->
                        val symbol = signal.tsCode?.trim().orEmpty().ifBlank { "unknown" }
                        "$symbol|${signal.signalTime.orEmpty()}|${signal.signalType.orEmpty()}|$index"
                    },
                    contentType = { _, _ -> "signal" },
                ) { _, signal ->
                    SignalTimelineCard(signal = signal, onOpenStockDetail = onOpenStockDetail)
                }
                if (displaySignals.size < filteredSignals.size) {
                    item(key = "signal_load_more_hint") {
                        DetailCard(
                            title = "正在加载更多信号",
                            lines = listOf("已显示 ${displaySignals.size}/${filteredSignals.size}"),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SignalSummaryCard(
    summary: SignalSummary,
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
            Text(summary.title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(summary.value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = TextPrimary)
            Text(summary.detail, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

@Composable
private fun SignalTimelineCard(
    signal: SignalItem,
    onOpenStockDetail: (String) -> Unit,
) {
    val tone = signalTone(signal.signalType)
    val railColor = when (tone) {
        PillTone.Positive -> Color(0xFF57B39B)
        PillTone.Negative -> Color(0xFFD2747E)
        PillTone.Neutral -> Color(0xFFE0B858)
    }
    val title = signal.name ?: signal.tsCode ?: "--"
    val tsCode = signal.tsCode?.trim().orEmpty()
    val code = tsCode.substringBefore(".").takeIf { it.isNotBlank() } ?: "--"
    Card(
        onClick = {
            if (tsCode.isNotBlank()) {
                onOpenStockDetail(tsCode)
            }
        },
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "$title，${signal.signalType ?: "信号"}" },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(18.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .width(6.dp)
                    .height(56.dp)
                    .background(railColor, RoundedCornerShape(999.dp)),
            )
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            text = "${signal.signalTime ?: "--"} · $code",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary,
                        )
                    }
                    StatusPill(text = signal.signalType ?: "信号", tone = tone)
                }
                val summary = buildList {
                    signal.triggerReason?.takeIf { it.isNotBlank() }?.let { add(it) }
                    signal.suggestion?.takeIf { it.isNotBlank() }?.let { add("建议：$it") }
                }.joinToString(" · ")
                if (summary.isNotBlank()) {
                    Text(
                        text = summary,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                        maxLines = 2,
                    )
                }
            }
        }
    }
}

private fun signalTone(signalType: String?): PillTone {
    val lower = signalType.orEmpty().lowercase()
    return when {
        "buy" in lower || "买" in signalType.orEmpty() -> PillTone.Positive
        "sell" in lower || "卖" in signalType.orEmpty() -> PillTone.Negative
        else -> PillTone.Neutral
    }
}

private const val SIGNAL_PAGE_SIZE = 40
private const val SIGNAL_PREFETCH_THRESHOLD = 8
