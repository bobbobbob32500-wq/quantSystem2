package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
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
import com.quant.system.ui.theme.ErrorDark
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.PrimaryDark
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import java.util.Locale
import kotlinx.coroutines.launch

private data class TradeOverviewCard(
    val id: String,
    val title: String,
    val value: String,
    val subtitle: String,
)

@OptIn(ExperimentalMaterial3Api::class)
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
    val overviewCards = remember(snapshot, trades, manualTradeRecords) {
        val openCount = snapshot?.virtualTrades?.openCount ?: trades.size
        val closedCount = snapshot?.virtualTrades?.closedCount ?: 0
        val winRate = snapshot?.virtualTrades?.stats?.winRatePct?.let { "${"%.1f".format(it)}%" } ?: "--"
        listOf(
            TradeOverviewCard(
                id = "open",
                title = "当前持仓",
                value = "$openCount",
                subtitle = "已平仓 $closedCount",
            ),
            TradeOverviewCard(
                id = "win_rate",
                title = "胜率",
                value = winRate,
                subtitle = "策略统计",
            ),
            TradeOverviewCard(
                id = "manual",
                title = "手动记录",
                value = "${manualTradeRecords.size}",
                subtitle = "卖出/复盘登记",
            ),
        )
    }
    val subtitle by remember(snapshot) {
        derivedStateOf {
            "持有 ${snapshot?.virtualTrades?.openCount ?: 0} · 已平 ${snapshot?.virtualTrades?.closedCount ?: 0}"
        }
    }
    var showAddModal by remember { mutableStateOf(false) }
    var editingTrade by remember { mutableStateOf<Trade?>(null) }
    var managingTrade by remember { mutableStateOf<Trade?>(null) }
    var pendingDeleteTrade by remember { mutableStateOf<Trade?>(null) }
    val sheetState = rememberModalBottomSheetState()
    val scope = rememberCoroutineScope()

    Box(modifier = Modifier.fillMaxSize()) {
        RefreshContainer(isRefreshing = isRefreshing, onRefresh = onRefresh) {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                item { TopBar(title = "持仓管理", subtitle = subtitle) }
                if (!message.isNullOrBlank()) {
                    item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
                }

                item {
                    HeroSection(
                        title = "交易概览",
                        value = "${snapshot?.virtualTrades?.openCount ?: trades.size}",
                        subtitle = "新增、编辑、备注、止盈止损、手动卖出一体化管理",
                        stats = listOf(
                            Triple("已平", "${snapshot?.virtualTrades?.closedCount ?: 0}", ""),
                            Triple("胜率", snapshot?.virtualTrades?.stats?.winRatePct?.let { "${"%.1f".format(it)}%" } ?: "--", ""),
                            Triple("记录", "${manualTradeRecords.size}", ""),
                        ),
                    )
                }

                item { SectionHeader("核心指标") }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        overviewCards.forEach { card ->
                            TradeOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                        }
                    }
                }

                item { SectionHeader("持仓列表") }
                if (trades.isEmpty()) {
                    item { EmptyStateCard("当前暂无持仓，请先新增模拟持仓。") }
                } else {
                    items(
                        items = trades,
                        key = { it.tradeId ?: it.symbol ?: it.name ?: it.hashCode().toString() },
                        contentType = { "trade" },
                    ) { trade ->
                        TradeCard(
                            trade = trade,
                            note = trade.tradeId?.let { tradeNotes[it] }.orEmpty(),
                            reminder = trade.tradeId?.let { tradeReminders[it] },
                            onEdit = { editingTrade = trade },
                            onDelete = {
                                pendingDeleteTrade = trade
                            },
                            onManage = { managingTrade = trade },
                        )
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

        FloatingActionButton(
            onClick = { showAddModal = true },
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(20.dp)
                .semantics { contentDescription = "新增持仓" },
            containerColor = Primary,
            shape = CircleShape,
        ) {
            Icon(Icons.Default.Add, contentDescription = "新增持仓", tint = Color.White)
        }
    }

    if (showAddModal) {
        ModalBottomSheet(onDismissRequest = { showAddModal = false }, sheetState = sheetState, containerColor = Surface) {
            AddTradeModalContent(
                onDismiss = {
                    scope.launch { sheetState.hide() }.invokeOnCompletion {
                        if (!sheetState.isVisible) showAddModal = false
                    }
                },
                onSubmit = { symbol, name, buyPrice, quantity ->
                    onAddTrade(symbol, name, buyPrice, quantity)
                    scope.launch { sheetState.hide() }.invokeOnCompletion {
                        if (!sheetState.isVisible) showAddModal = false
                    }
                },
            )
        }
    }

    if (editingTrade != null) {
        ModalBottomSheet(onDismissRequest = { editingTrade = null }, sheetState = sheetState, containerColor = Surface) {
            AddTradeModalContent(
                title = "编辑持仓",
                submitLabel = "确认更新",
                initialCode = editingTrade?.symbol.orEmpty(),
                initialName = editingTrade?.name.orEmpty(),
                initialCostPrice = (editingTrade?.buyPrice ?: editingTrade?.holdPrice)?.toString().orEmpty(),
                initialQuantity = "",
                onDismiss = {
                    scope.launch { sheetState.hide() }.invokeOnCompletion {
                        if (!sheetState.isVisible) editingTrade = null
                    }
                },
                onSubmit = { symbol, name, buyPrice, quantity ->
                    editingTrade?.tradeId?.let { tradeId ->
                        onUpdateTrade(tradeId, symbol, name, buyPrice, quantity)
                    }
                    scope.launch { sheetState.hide() }.invokeOnCompletion {
                        if (!sheetState.isVisible) editingTrade = null
                    }
                },
            )
        }
    }

    if (managingTrade != null) {
        val trade = managingTrade ?: return
        ModalBottomSheet(onDismissRequest = { managingTrade = null }, containerColor = Surface) {
            TradeManageSheet(
                trade = trade,
                initialNote = trade.tradeId?.let { tradeNotes[it] }.orEmpty(),
                initialStopLoss = trade.tradeId?.let { tradeReminders[it]?.stopLossPct }?.toString().orEmpty(),
                initialTakeProfit = trade.tradeId?.let { tradeReminders[it]?.takeProfitPct }?.toString().orEmpty(),
                onSaveNote = { note -> trade.tradeId?.let { onSaveTradeNote(it, note) } },
                onSaveReminder = { stopLoss, takeProfit ->
                    trade.tradeId?.let { onSaveTradeReminder(it, stopLoss, takeProfit) }
                },
                onSaveSellRecord = { sellPrice, quantity, note ->
                    onAddManualSellRecord(
                        trade.symbol.orEmpty(),
                        trade.name.orEmpty(),
                        sellPrice,
                        quantity,
                        note,
                    )
                },
            )
        }
    }

    if (pendingDeleteTrade != null) {
        val trade = pendingDeleteTrade
        AlertDialog(
            onDismissRequest = { pendingDeleteTrade = null },
            title = { Text("确认删除持仓") },
            text = {
                Text(
                    "将删除 ${trade?.name ?: trade?.symbol ?: "该持仓"}，此操作不可撤销。",
                    color = TextSecondary,
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onDeleteTrade(trade?.tradeId?.takeIf { it.isNotBlank() })
                        pendingDeleteTrade = null
                    },
                ) {
                    Text("确认删除", color = ErrorDark, fontWeight = FontWeight.SemiBold)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDeleteTrade = null }) {
                    Text("取消", color = TextSecondary)
                }
            },
        )
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
        shape = RoundedCornerShape(14.dp),
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
private fun TradeCard(
    trade: Trade,
    note: String,
    reminder: TradeReminderSetting?,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onManage: () -> Unit,
) {
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
    val tone = when {
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
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = trade.name ?: "--",
                        style = MaterialTheme.typography.titleSmall,
                        color = TextPrimary,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(text = trade.symbol ?: "--", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    StatusPill(text = pnlPct?.let { "${"%.2f".format(it)}%" } ?: "--", tone = tone)
                    if (dayChangePct != null) {
                        StatusPill(text = "Day ${"%.2f".format(dayChangePct)}%", tone = dayTone)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                TradeMetric(label = "成本价", value = costPrice?.let { "%.2f".format(it) } ?: "--", modifier = Modifier.weight(1f))
                TradeMetric(label = "最新价", value = latestPrice?.let { "%.2f".format(it) } ?: "--", modifier = Modifier.weight(1f))
                TradeMetric(label = "更新", value = trade.lastTradeDate ?: "--", modifier = Modifier.weight(1f))
            }
            Text(
                text = "Updated: ${updatedAt ?: "--"}  |  Source: $priceSourceLabel",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            if (note.isNotBlank()) {
                DetailCard(title = "持仓备注", lines = listOf(note))
            }
            if (reminder?.stopLossPct != null || reminder?.takeProfitPct != null) {
                DetailCard(
                    title = "止盈止损提醒",
                    lines = listOf(
                        "止损：${reminder?.stopLossPct?.let { "${"%.2f".format(it)}%" } ?: "--"}",
                        "止盈：${reminder?.takeProfitPct?.let { "${"%.2f".format(it)}%" } ?: "--"}",
                    ),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onEdit, shape = RoundedCornerShape(10.dp)) {
                    Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp), tint = PrimaryDark)
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("编辑", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = PrimaryDark)
                }
                TextButton(onClick = onManage, shape = RoundedCornerShape(10.dp)) {
                    Text("备注/提醒/卖出记录", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = PrimaryDark)
                }
                TextButton(onClick = onDelete, shape = RoundedCornerShape(10.dp)) {
                    Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(18.dp), tint = ErrorDark)
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("删除", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = ErrorDark)
                }
            }
        }
    }
}

@Composable
private fun TradeMetric(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(text = label, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
        Text(text = value, style = MaterialTheme.typography.bodyMedium, color = TextPrimary, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun AddTradeModalContent(
    title: String = "新增持仓",
    submitLabel: String = "确认新增",
    initialCode: String = "",
    initialName: String = "",
    initialCostPrice: String = "",
    initialQuantity: String = "",
    onDismiss: () -> Unit,
    onSubmit: (symbol: String, name: String, buyPrice: Double, quantity: Int) -> Unit,
) {
    var code by remember(initialCode) { mutableStateOf(initialCode) }
    var name by remember(initialName) { mutableStateOf(initialName) }
    var costPrice by remember(initialCostPrice) { mutableStateOf(initialCostPrice) }
    var quantity by remember(initialQuantity) { mutableStateOf(initialQuantity) }
    var codeError by remember { mutableStateOf<String?>(null) }
    var nameError by remember { mutableStateOf<String?>(null) }
    var priceError by remember { mutableStateOf<String?>(null) }
    var quantityError by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = title, style = MaterialTheme.typography.headlineSmall, color = TextPrimary, fontWeight = FontWeight.Bold)
            TextButton(onClick = onDismiss) { Text("取消", color = TextSecondary) }
        }

        OutlinedTextField(
            value = code,
            onValueChange = { code = it; codeError = null },
            label = { Text("股票代码") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            isError = codeError != null,
            supportingText = { if (codeError != null) Text(codeError ?: "") },
        )
        OutlinedTextField(
            value = name,
            onValueChange = { name = it; nameError = null },
            label = { Text("股票名称") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            isError = nameError != null,
            supportingText = { if (nameError != null) Text(nameError ?: "") },
        )
        OutlinedTextField(
            value = costPrice,
            onValueChange = { costPrice = it; priceError = null },
            label = { Text("成本价") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            isError = priceError != null,
            supportingText = { if (priceError != null) Text(priceError ?: "") },
        )
        OutlinedTextField(
            value = quantity,
            onValueChange = { quantity = it; quantityError = null },
            label = { Text("持仓数量") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            isError = quantityError != null,
            supportingText = { if (quantityError != null) Text(quantityError ?: "") },
        )

        PrimaryButton(
            text = submitLabel,
            onClick = {
                val price = costPrice.toDoubleOrNull()
                val qty = quantity.toIntOrNull() ?: 0
                val normalizedCode = code.trim().uppercase(Locale.getDefault())
                val normalizedName = name.trim()
                codeError = if (normalizedCode.isBlank()) "请输入股票代码" else null
                nameError = if (normalizedName.isBlank()) "请输入股票名称" else null
                priceError = if (price == null || price <= 0.0) "请输入大于 0 的成本价" else null
                quantityError = if (quantity.isBlank() || qty <= 0) "持仓数量需为正整数" else null
                if (codeError != null || nameError != null || priceError != null || quantityError != null) {
                    return@PrimaryButton
                }
                onSubmit(normalizedCode, normalizedName, price ?: return@PrimaryButton, qty)
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun TradeManageSheet(
    trade: Trade,
    initialNote: String,
    initialStopLoss: String,
    initialTakeProfit: String,
    onSaveNote: (String) -> Unit,
    onSaveReminder: (Double?, Double?) -> Unit,
    onSaveSellRecord: (Double, Int, String?) -> Unit,
) {
    var note by remember(initialNote) { mutableStateOf(initialNote) }
    var stopLoss by remember(initialStopLoss) { mutableStateOf(initialStopLoss) }
    var takeProfit by remember(initialTakeProfit) { mutableStateOf(initialTakeProfit) }
    var sellPrice by remember { mutableStateOf("") }
    var sellQty by remember { mutableStateOf("") }
    var sellNote by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = "管理 ${trade.name ?: trade.symbol.orEmpty()}",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        OutlinedTextField(
            value = note,
            onValueChange = { note = it },
            label = { Text("持仓备注") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedButton(onClick = { onSaveNote(note) }, modifier = Modifier.fillMaxWidth()) { Text("保存备注") }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = stopLoss,
                onValueChange = { stopLoss = it },
                label = { Text("止损%") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
            OutlinedTextField(
                value = takeProfit,
                onValueChange = { takeProfit = it },
                label = { Text("止盈%") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
        }
        OutlinedButton(
            onClick = { onSaveReminder(stopLoss.toDoubleOrNull(), takeProfit.toDoubleOrNull()) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("保存止盈止损提醒")
        }

        DetailCard(title = "卖出后复盘入口", lines = listOf("先登记卖出记录，再到执行历史查看闭环结果"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = sellPrice,
                onValueChange = { sellPrice = it },
                label = { Text("卖出价") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
            OutlinedTextField(
                value = sellQty,
                onValueChange = { sellQty = it },
                label = { Text("卖出数量") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
        }
        OutlinedTextField(
            value = sellNote,
            onValueChange = { sellNote = it },
            label = { Text("卖出备注") },
            modifier = Modifier.fillMaxWidth(),
        )
        PrimaryButton(
            text = "保存卖出记录并跳转复盘",
            onClick = {
                val price = sellPrice.toDoubleOrNull() ?: return@PrimaryButton
                val qty = sellQty.toIntOrNull() ?: return@PrimaryButton
                onSaveSellRecord(price, qty, sellNote.takeIf { it.isNotBlank() })
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
