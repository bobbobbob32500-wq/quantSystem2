package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.ManualTradeRecord
import com.quant.system.data.model.Trade
import com.quant.system.data.model.TradeReminderSetting
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import java.util.Locale

private data class TradeOverviewCard(
    val title: String,
    val value: String,
    val subtitle: String,
)

private data class StrategyTradeGroup(
    val key: String,
    val label: String,
    val openTrades: List<Trade>,
    val closedTrades: List<Trade>,
    val winRatePct: Double?,
    val tradeCount: Int,
)

@Suppress("UNUSED_PARAMETER")
@Composable
fun TradesScreen(
    snapshot: DashboardSnapshot?,
    isRefreshing: Boolean,
    message: String?,
    noticeType: NoticeType,
    tradeNotes: Map<String, String>,
    tradeReminders: Map<String, TradeReminderSetting>,
    manualTradeRecords: List<ManualTradeRecord>,
    onRefresh: () -> Unit,
    onAddTrade: (symbol: String, name: String, buyPrice: Double, quantity: Int) -> Unit,
    onUpdateTrade: (tradeId: String, symbol: String, name: String, buyPrice: Double, quantity: Int) -> Unit,
    onDeleteTrade: (tradeId: String?) -> Unit,
    onSaveTradeNote: (tradeId: String, note: String) -> Unit,
    onSaveTradeReminder: (tradeId: String, stopLossPct: Double?, takeProfitPct: Double?) -> Unit,
    onAddManualSellRecord: (symbol: String, name: String, sellPrice: Double, quantity: Int, note: String?) -> Unit,
) {
    val trades = snapshot?.virtualTrades?.openTrades.orEmpty()
    val recentClosed = snapshot?.virtualTrades?.recentClosed.orEmpty()
    val strategyGroups = remember(trades, recentClosed) {
        val openByStrategy = trades.groupBy { resolveTradeStrategyKey(it) }
        val closedByStrategy = recentClosed.groupBy { resolveTradeStrategyKey(it) }
        (openByStrategy.keys + closedByStrategy.keys)
            .toSet()
            .map { key ->
                val openTrades = openByStrategy[key].orEmpty()
                val closedTrades = closedByStrategy[key].orEmpty()
                val closedWithPnl = closedTrades.mapNotNull { it.pnlPct }
                val winRatePct = if (closedWithPnl.isNotEmpty()) {
                    closedWithPnl.count { it > 0.0 } * 100.0 / closedWithPnl.size.toDouble()
                } else {
                    null
                }
                StrategyTradeGroup(
                    key = key,
                    label = strategyLabelFromKey(key),
                    openTrades = openTrades,
                    closedTrades = closedTrades,
                    winRatePct = winRatePct,
                    tradeCount = openTrades.size + closedTrades.size,
                )
            }
            .filter { it.openTrades.isNotEmpty() || it.closedTrades.isNotEmpty() }
            .sortedWith(
                compareByDescending<StrategyTradeGroup> { it.openTrades.size }
                    .thenByDescending { it.tradeCount }
                    .thenBy { it.label },
            )
    }
    val overviewCards = remember(snapshot, trades, strategyGroups) {
        val openCount = snapshot?.virtualTrades?.openCount ?: trades.size
        val closedCount = snapshot?.virtualTrades?.closedCount ?: recentClosed.size
        val winRate = snapshot?.virtualTrades?.stats?.winRatePct?.let { "${"%.1f".format(it)}%" } ?: "--"
        listOf(
            TradeOverviewCard("当前持仓", "$openCount", "已平仓 $closedCount"),
            TradeOverviewCard("胜率", winRate, "策略统计"),
            TradeOverviewCard("策略分组", "${strategyGroups.size}", "按策略查看"),
        )
    }
    val subtitle by remember(snapshot, strategyGroups) {
        derivedStateOf { "只读账本 · 持有 ${snapshot?.virtualTrades?.openCount ?: 0} · 策略 ${strategyGroups.size} 组" }
    }

    RefreshContainer(isRefreshing = isRefreshing, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }

            item {
                HeroSection(
                    title = "持仓账本",
                    value = "${snapshot?.virtualTrades?.openCount ?: trades.size}",
                    subtitle = subtitle,
                    stats = listOf(
                        Triple("已平", "${snapshot?.virtualTrades?.closedCount ?: recentClosed.size}", ""),
                        Triple("胜率", snapshot?.virtualTrades?.stats?.winRatePct?.let { "${"%.1f".format(it)}%" } ?: "--", ""),
                        Triple("策略", "${strategyGroups.size}", ""),
                    ),
                )
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    overviewCards.forEach { card ->
                        TradeOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                    }
                }
            }

            item { SectionHeader("按策略持仓") }
            if (trades.isEmpty()) {
                item { EmptyStateCard("当前暂无持仓。") }
            } else {
                strategyGroups.forEach { group ->
                    item(key = "strategy_group_${group.key}") {
                        StrategyGroupCard(group = group)
                    }
                    items(
                        items = group.openTrades,
                        key = { trade -> trade.tradeId ?: "${group.key}_${trade.symbol ?: trade.name ?: trade.hashCode()}" },
                        contentType = { "trade_${group.key}" },
                    ) { trade ->
                        TradeLedgerCard(trade = trade)
                    }
                }
            }

            item { SectionHeader("最近平仓") }
            if (recentClosed.isEmpty()) {
                item { EmptyStateCard("暂无最近平仓记录。") }
            } else {
                items(
                    items = recentClosed.take(8),
                    key = { it.tradeId ?: "${it.symbol}_${it.sellTime ?: it.buyTime}" },
                    contentType = { "recent_closed" },
                ) { trade ->
                    ClosedTradeCard(trade = trade)
                }
            }

            if (manualTradeRecords.isNotEmpty()) {
                item { SectionHeader("最近手动成交") }
                items(manualTradeRecords.take(8), key = { "${it.executedAt}_${it.symbol}_${it.action}" }) { record ->
                    DetailCard(
                        title = "${record.symbol} ${record.name}",
                        lines = buildList {
                            add("${record.action.uppercase()} · 价格 ${"%.2f".format(record.price)} · 数量 ${record.quantity}")
                            add("时间：${record.executedAt}")
                            record.note?.takeIf { it.isNotBlank() }?.let { add("备注：$it") }
                        },
                    )
                }
            }

            item { Spacer(modifier = Modifier.padding(bottom = 80.dp)) }
        }
    }
}

@Composable
private fun StrategyGroupCard(group: StrategyTradeGroup) {
    val strategyTone = strategyGroupTone(group.key)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = strategyTone.container),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, strategyTone.border),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = group.label,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary,
                    )
                    StatusPill(
                        text = strategyTone.tag,
                        tone = PillTone.Neutral,
                    )
                    Text(
                        text = "当前持仓 ${group.openTrades.size} · 总交易 ${group.tradeCount}",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(
                    text = group.winRatePct?.let { "胜率 ${"%.1f".format(it)}%" } ?: "胜率 --",
                    tone = group.winRatePct?.let { if (it >= 50.0) PillTone.Positive else PillTone.Negative } ?: PillTone.Neutral,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TradeMetricCard(label = "持仓数", value = "${group.openTrades.size}", modifier = Modifier.weight(1f))
                TradeMetricCard(label = "交易次数", value = "${group.tradeCount}", modifier = Modifier.weight(1f))
                TradeMetricCard(
                    label = "已平仓",
                    value = "${group.closedTrades.size}",
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun TradeOverviewCardItem(
    card: TradeOverviewCard,
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
private fun TradeLedgerCard(trade: Trade) {
    val latestPrice = trade.currentPrice ?: trade.lastPrice
    val costPrice = trade.buyPrice ?: trade.holdPrice
    val pnlPct = trade.lastPnlPct ?: trade.profitPct
    val dayChangePct = trade.quotePctChange
    val updatedAt = trade.quoteTime ?: trade.lastTradeDate
    val priceSourceLabel = when (trade.priceSource) {
        "realtime" -> "Realtime"
        "cached_realtime" -> "Cached Realtime"
        "daily_close" -> "Daily Close Fallback"
        else -> "Unknown"
    }
    val pnlTone = when {
        (pnlPct ?: 0.0) > 0 -> PillTone.Positive
        (pnlPct ?: 0.0) < 0 -> PillTone.Negative
        else -> PillTone.Neutral
    }
    val dayTone = when {
        (dayChangePct ?: 0.0) > 0 -> PillTone.Positive
        (dayChangePct ?: 0.0) < 0 -> PillTone.Negative
        else -> PillTone.Neutral
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "${trade.name ?: "--"} ${trade.symbol ?: "--"}" },
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
                        text = trade.symbol?.takeLast(2) ?: "仓",
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
                        text = trade.name ?: "--",
                        style = MaterialTheme.typography.titleSmall,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = trade.symbol ?: "--",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    StatusPill(text = pnlPct?.let { "${"%.2f".format(it)}%" } ?: "--", tone = pnlTone)
                    if (dayChangePct != null) {
                        StatusPill(text = "Day ${"%.2f".format(dayChangePct)}%", tone = dayTone)
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TradeMetricCard(
                    label = "成本价",
                    value = costPrice?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
                TradeMetricCard(
                    label = "现价",
                    value = latestPrice?.let { "%.2f".format(it) } ?: "--",
                    modifier = Modifier.weight(1f),
                )
                TradeMetricCard(
                    label = "收益",
                    value = pnlPct?.let { "${"%.2f".format(it)}%" } ?: "--",
                    modifier = Modifier.weight(1f),
                )
            }

            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
                shape = RoundedCornerShape(18.dp),
            ) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("买入时间：${trade.buyTime ?: "--"}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                    Text("更新时间：${updatedAt ?: "--"}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                    Text("价格来源：$priceSourceLabel", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                }
            }
        }
    }
}

@Composable
private fun ClosedTradeCard(trade: Trade) {
    val pnlPct = trade.pnlPct
    val tone = when {
        (pnlPct ?: 0.0) > 0 -> PillTone.Positive
        (pnlPct ?: 0.0) < 0 -> PillTone.Negative
        else -> PillTone.Neutral
    }
    val title = listOfNotNull(trade.symbol, trade.name).joinToString(" ").ifBlank { "--" }
    val strategySummary = trade.strategyLabel
        ?: trade.strategyProfile
        ?: trade.signalSubtype
        ?: trade.buySignal
        ?: "--"

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "最近平仓 ${trade.name ?: "--"} ${trade.symbol ?: "--"}" },
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(22.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleSmall,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "策略：$strategySummary",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(text = pnlPct?.let { "${"%.2f".format(it)}%" } ?: "--", tone = tone)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TradeMetricCard(label = "买入价", value = trade.buyPrice?.let { "%.2f".format(it) } ?: "--", modifier = Modifier.weight(1f))
                TradeMetricCard(label = "卖出价", value = trade.sellPrice?.let { "%.2f".format(it) } ?: "--", modifier = Modifier.weight(1f))
                TradeMetricCard(label = "持有", value = trade.holdDurationLabel ?: "--", modifier = Modifier.weight(1f))
            }
            DetailCard(
                title = "卖点信息",
                lines = listOf(
                    "卖出原因：${sellReasonLabel(trade.sellReason)}",
                    "卖出时间：${trade.sellTime ?: "--"}",
                    "买点说明：${trade.buySignal ?: "--"}",
                ),
            )
        }
    }
}

@Composable
private fun TradeMetricCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(text = label, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
            Text(text = value, style = MaterialTheme.typography.titleSmall, color = TextPrimary, fontWeight = FontWeight.Bold)
        }
    }
}

private fun sellReasonLabel(raw: String?): String {
    return when (raw?.lowercase(Locale.ROOT)) {
        "time_exit" -> "超时卖点"
        "take_profit" -> "止盈"
        "stop_loss" -> "止损"
        "break_even_stop" -> "保本止盈"
        "trailing_stop" -> "移动止盈"
        "manual_close" -> "手动平仓"
        null, "" -> "--"
        else -> raw
    }
}

private fun resolveTradeStrategyKey(trade: Trade): String {
    val raw = trade.strategyProfile
        ?: trade.strategyLabel
        ?: trade.buyRoute
        ?: trade.signalSubtype
        ?: trade.buySignal
    return normalizedTradeStrategyKey(raw) ?: "unknown"
}

private fun normalizedTradeStrategyKey(raw: String?): String? {
    val value = raw?.trim()?.lowercase(Locale.ROOT)?.replace("-", "_") ?: return null
    return when {
        value.isBlank() -> null
        value.contains("secondary_launch") || value.contains("二次") -> "secondary_launch"
        value.contains("wide_breakout")
            || value.contains("breakout_wide")
            || (value.contains("wide") && value.contains("breakout"))
            || value.contains("宽进")
            || value.contains("宽突破") -> "wide_breakout"
        value.contains("breakout") || value.contains("突破") -> "breakout"
        value.contains("alpha158") || value.contains("alpha_158") -> "alpha158"
        value.contains("legacy") || value.contains("原策略") -> "legacy"
        value.contains("both") || value.contains("融合") -> "both"
        else -> value
    }
}

private data class StrategyGroupTone(
    val container: Color,
    val border: Color,
    val tag: String,
)

private fun strategyGroupTone(key: String): StrategyGroupTone {
    return when (key) {
        "secondary_launch" -> StrategyGroupTone(
            container = Color(0xFFEFF7FF),
            border = Color(0xFFB4D4FF),
            tag = "二次启动策略",
        )
        "breakout" -> StrategyGroupTone(
            container = Color(0xFFFFF3E9),
            border = Color(0xFFFFCC9A),
            tag = "突破策略",
        )
        "wide_breakout" -> StrategyGroupTone(
            container = Color(0xFFEAFBF5),
            border = Color(0xFFAEE9CF),
            tag = "宽进突破策略",
        )
        "alpha158" -> StrategyGroupTone(
            container = Color(0xFFF4EFFF),
            border = Color(0xFFD3C2FF),
            tag = "Alpha158策略",
        )
        else -> StrategyGroupTone(
            container = Surface,
            border = Border.copy(alpha = 0.72f),
            tag = "其他策略",
        )
    }
}

private fun strategyLabelFromKey(key: String): String {
    return when (key) {
        "secondary_launch" -> "二次启动"
        "breakout" -> "突破策略"
        "wide_breakout" -> "宽进突破"
        "alpha158" -> "Alpha158"
        "legacy" -> "原策略"
        "both" -> "融合策略"
        "unknown" -> "未标注策略"
        else -> key
    }
}
