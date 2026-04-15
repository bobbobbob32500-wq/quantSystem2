package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.AlertItem
import com.quant.system.data.model.AlertSummary

@Composable
fun AlertCenterScreen(
    alerts: List<AlertItem>,
    summary: AlertSummary?,
    onAckAlert: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(title = "预警中心", subtitle = "多维度智能预警监控")
        }

        // 预警摘要
        if (summary != null) {
            item {
                AlertSummaryCard(summary)
            }
        }

        // 按级别分组显示
        val criticalAlerts = alerts.filter { it.level == "critical" }
        val highAlerts = alerts.filter { it.level == "high" }
        val mediumAlerts = alerts.filter { it.level in listOf("medium", "low", "info") }

        if (criticalAlerts.isNotEmpty()) {
            item { SectionHeader("紧急预警", Color(0xFFDC2626)) }
            items(criticalAlerts, key = { it.id }) { alert ->
                AlertCard(alert, onAck = { onAckAlert(alert.id) })
            }
        }

        if (highAlerts.isNotEmpty()) {
            item { SectionHeader("高优先级", Color(0xFFF59E0B)) }
            items(highAlerts, key = { it.id }) { alert ->
                AlertCard(alert, onAck = { onAckAlert(alert.id) })
            }
        }

        if (mediumAlerts.isNotEmpty()) {
            item { SectionHeader("一般预警", Color(0xFF3B82F6)) }
            items(mediumAlerts, key = { it.id }) { alert ->
                AlertCard(alert, onAck = { onAckAlert(alert.id) })
            }
        }

        if (alerts.isEmpty()) {
            item {
                EmptyStateCard("暂无活跃预警，系统运行正常")
            }
        }

        item {
            SecondaryButton(
                text = "刷新预警",
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun AlertSummaryCard(summary: AlertSummary) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (summary.hasCritical) Color(0xFFFEE2E2) else Color(0xFFF0FDF4)
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceEvenly
        ) {
            SummaryStat("活跃", summary.totalActive.toString(), if (summary.hasCritical) Color.Red else Color(0xFF22C55E))
            SummaryStat("紧急", (summary.byLevel["critical"] ?: 0).toString(), Color(0xFFDC2626))
            SummaryStat("技术", (summary.byType["technical"] ?: 0).toString(), Color(0xFF3B82F6))
            SummaryStat("资金", (summary.byType["capital_flow"] ?: 0).toString(), Color(0xFFF59E0B))
            SummaryStat("风控", (summary.byType["risk"] ?: 0).toString(), Color(0xFF8B5CF6))
        }
    }
}

@Composable
private fun SummaryStat(label: String, value: String, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = color)
        Text(label, fontSize = 11.sp, color = Color.Gray)
    }
}

@Composable
private fun SectionHeader(title: String, color: Color) {
    Row(
        modifier = Modifier.padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(modifier = Modifier.size(8.dp).background(color, RoundedCornerShape(4.dp)))
        Spacer(modifier = Modifier.width(8.dp))
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun AlertCard(alert: AlertItem, onAck: () -> Unit) {
    val levelColor = when (alert.level) {
        "critical" -> Color(0xFFDC2626)
        "high" -> Color(0xFFF59E0B)
        "medium" -> Color(0xFF3B82F6)
        else -> Color.Gray
    }

    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(modifier = Modifier.size(6.dp).background(levelColor, RoundedCornerShape(3.dp)))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(alert.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                }
                Text(alert.type, fontSize = 11.sp, color = Color.Gray)
            }

            Text(alert.message, style = MaterialTheme.typography.bodyMedium)

            if (alert.action.isNotBlank()) {
                Text("建议: ${alert.action}", fontSize = 12.sp, color = Color(0xFF6366F1))
            }

            if (!alert.acked) {
                TextButton(onClick = onAck) {
                    Text("确认预警", fontSize = 12.sp)
                }
            }
        }
    }
}
