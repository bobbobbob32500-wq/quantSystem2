package com.quant.system.ui.screen

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.PriceAlertItem
import com.quant.system.data.model.WatcherSummary

@Composable
fun RealtimeWatcherScreen(
    alerts: List<PriceAlertItem>,
    summary: WatcherSummary?,
    onRemoveAlert: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(title = "实时盯盘", subtitle = "关键价位提醒、异常波动监控")
        }

        // 摘要
        if (summary != null) {
            item {
                Card {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        horizontalArrangement = Arrangement.SpaceEvenly
                    ) {
                        WatcherStat("总提醒", summary.totalAlerts)
                        WatcherStat("活跃", summary.activeAlerts)
                        WatcherStat("已触发", summary.triggeredAlerts)
                        WatcherStat("异动", summary.recentEvents)
                    }
                }
            }
        }

        // 已触发的提醒
        val triggered = alerts.filter { it.triggered }
        val active = alerts.filter { !it.triggered }

        if (triggered.isNotEmpty()) {
            item {
                Text("已触发", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, color = Color(0xFFDC2626))
            }
            items(triggered, key = { it.id }) { alert ->
                PriceAlertCard(alert, isTriggered = true, onRemove = { onRemoveAlert(alert.id) })
            }
        }

        // 活跃提醒
        if (active.isNotEmpty()) {
            item {
                Text("活跃提醒", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, color = Color(0xFF22C55E))
            }
            items(active, key = { it.id }) { alert ->
                PriceAlertCard(alert, isTriggered = false, onRemove = { onRemoveAlert(alert.id) })
            }
        }

        if (alerts.isEmpty()) {
            item {
                EmptyStateCard("暂无盯盘提醒，可在持仓页设置止损止盈提醒")
            }
        }

        item {
            SecondaryButton(text = "刷新", onClick = onRefresh, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun WatcherStat(label: String, value: Int) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value.toString(), fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text(label, fontSize = 11.sp, color = Color.Gray)
    }
}

@Composable
private fun PriceAlertCard(alert: PriceAlertItem, isTriggered: Boolean, onRemove: () -> Unit) {
    val typeLabel = when (alert.watchType) {
        "price_above" -> "上穿"
        "price_below" -> "下穿"
        "support_break" -> "跌破支撑"
        "resistance_break" -> "突破阻力"
        else -> alert.watchType
    }

    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (isTriggered) Color(0xFFFEE2E2) else MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(alert.label.ifBlank { "${alert.symbol} $typeLabel ${alert.targetValue}" },
                    style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(typeLabel, fontSize = 12.sp, color = Color(0xFF6366F1))
                    Text("目标: ${alert.targetValue}", fontSize = 12.sp, color = Color.Gray)
                    if (isTriggered) {
                        Text("已触发!", fontSize = 12.sp, color = Color.Red, fontWeight = FontWeight.Bold)
                    }
                }
            }
            TextButton(onClick = onRemove) {
                Text("移除", fontSize = 12.sp, color = Color.Gray)
            }
        }
    }
}
