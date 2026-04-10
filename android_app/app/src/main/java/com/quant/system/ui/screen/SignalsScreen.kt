package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
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
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.SignalItem
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class SignalOverviewCard(
    val id: String,
    val title: String,
    val value: String,
    val subtitle: String,
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
    var query by rememberSaveable { mutableStateOf("") }
    var selectedType by rememberSaveable { mutableStateOf("全部") }

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

    val positiveCount = remember(signals) {
        signals.count { s ->
            val lower = s.signalType.orEmpty().lowercase()
            "buy" in lower || "买" in s.signalType.orEmpty()
        }
    }
    val negativeCount = remember(signals) {
        signals.count { s ->
            val lower = s.signalType.orEmpty().lowercase()
            "sell" in lower || "卖" in s.signalType.orEmpty()
        }
    }
    val overviewCards = remember(signals, positiveCount, negativeCount) {
        listOf(
            SignalOverviewCard(
                id = "total",
                title = "最近信号",
                value = "${signals.size}",
                subtitle = "当前批次总量",
            ),
            SignalOverviewCard(
                id = "positive",
                title = "偏多",
                value = "$positiveCount",
                subtitle = "买入/看多",
            ),
            SignalOverviewCard(
                id = "negative",
                title = "偏空",
                value = "$negativeCount",
                subtitle = "卖出/减仓",
            ),
        )
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
                    title = "信号中心",
                    subtitle = snapshot?.signals?.latestSignalLabel ?: "按类型筛选并快速查看个股",
                )
            }
            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }
            if (isRefreshing && signals.isEmpty()) {
                items(5) { LoadingSkeletonCard() }
                return@LazyColumn
            }

            item {
                HeroSection(
                    title = "信号概览",
                    value = "${signals.size}",
                    subtitle = "点击卡片可继续筛选和查看详情",
                    stats = listOf(
                        Triple("偏多", "$positiveCount", ""),
                        Triple("偏空", "$negativeCount", ""),
                        Triple("类型", "${signalTypes.size - 1}", ""),
                    ),
                )
            }

            item { SectionHeader("筛选条件") }
            item {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .semantics { contentDescription = "搜索信号" },
                    singleLine = true,
                    label = { Text("搜索名称/代码/类型/触发原因") },
                )
            }
            item {
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

            item { SectionHeader("信号列表") }
            if (filteredSignals.isEmpty()) {
                item { EmptyStateCard("当前筛选条件下没有匹配信号，请调整关键词或类型。") }
            } else {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        overviewCards.forEach { card ->
                            SignalOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                        }
                    }
                }
                items(
                    items = filteredSignals,
                    key = { "${it.tsCode.orEmpty()}_${it.signalTime.orEmpty()}_${it.signalType.orEmpty()}" },
                    contentType = { "signal" },
                ) { signal ->
                    SignalCard(signal = signal, onOpenStockDetail = onOpenStockDetail)
                }
            }
        }
    }
}

@Composable
private fun SignalOverviewCardItem(
    card: SignalOverviewCard,
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

@Composable
private fun SignalCard(
    signal: SignalItem,
    onOpenStockDetail: (String) -> Unit,
) {
    Card(
        onClick = { onOpenStockDetail(signal.tsCode ?: "") },
        modifier = Modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "${signal.name ?: signal.tsCode ?: "--"}，${signal.signalType ?: "信号"}"
            },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(16.dp),
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
                        text = signal.name ?: signal.tsCode ?: "--",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = listOfNotNull(signal.tsCode, signal.signalTime).joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                SharedSignalTypeBadge(signal.signalType ?: "信号")
            }
            signal.triggerReason?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = "触发原因：$it",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextPrimary,
                )
            }
            signal.suggestion?.takeIf { it.isNotBlank() }?.let {
                DetailCard(title = "建议动作", lines = listOf(it))
            }
        }
    }
}

@Composable
private fun SharedSignalTypeBadge(signalType: String) {
    val lower = signalType.lowercase()
    val tone = when {
        "buy" in lower || "买" in signalType -> PillTone.Positive
        "sell" in lower || "卖" in signalType -> PillTone.Negative
        else -> PillTone.Neutral
    }
    StatusPill(text = signalType, tone = tone)
}
