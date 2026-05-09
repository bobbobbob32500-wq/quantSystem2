package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.ButlerAnalysisItem
import com.quant.system.ui.theme.Background
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

@Composable
fun AIAssistantScreen(
    butlerAnalysisItems: List<ButlerAnalysisItem>,
) {
    var expandedItemType by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        TopBar(
            title = "AI 分析记录",
            subtitle = "盘前简报、盘中监控、盘后复盘、风险检查、信号分析",
            eyebrow = "AI Analysis",
        )

        if (butlerAnalysisItems.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = "暂无分析记录",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextSecondary,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "AI 管家生成的分析结果将显示在这里",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary.copy(alpha = 0.6f),
                        textAlign = TextAlign.Center,
                    )
                }
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(butlerAnalysisItems, key = { "${it.type}_${it.generatedAt}" }) { item ->
                    AnalysisItemCard(
                        item = item,
                        isExpanded = expandedItemType == item.type,
                        onToggle = {
                            expandedItemType = if (expandedItemType == item.type) null else item.type
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun AnalysisItemCard(
    item: ButlerAnalysisItem,
    isExpanded: Boolean,
    onToggle: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = typeLabel(item.type),
                    style = MaterialTheme.typography.labelMedium,
                    color = when (item.type) {
                        "briefing" -> androidx.compose.ui.graphics.Color(0xFF4CAF50)
                        "monitor" -> androidx.compose.ui.graphics.Color(0xFF2196F3)
                        "review" -> androidx.compose.ui.graphics.Color(0xFFFF9800)
                        "risk_check" -> androidx.compose.ui.graphics.Color(0xFFF44336)
                        "signal_analysis" -> androidx.compose.ui.graphics.Color(0xFF9C27B0)
                        "candidate_analysis" -> androidx.compose.ui.graphics.Color(0xFF00BCD4)
                        else -> TextSecondary
                    },
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = formatTime(item.generatedAt),
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary,
                )
            }

            Text(
                text = item.title,
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.SemiBold,
            )

            Text(
                text = item.summary,
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary,
                maxLines = if (isExpanded) Int.MAX_VALUE else 3,
            )

            if (isExpanded && item.detail != null) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Text(
                        text = item.detail.toString(),
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                        modifier = Modifier.padding(12.dp),
                    )
                }
            }
        }
    }
}

private fun typeLabel(type: String): String = when (type) {
    "briefing" -> "盘前简报"
    "monitor" -> "盘中监控"
    "review" -> "盘后复盘"
    "risk_check" -> "风险检查"
    "signal_analysis" -> "信号分析"
    "candidate_analysis" -> "今日候选"
    else -> type
}

private fun formatTime(iso: String): String {
    return try {
        iso.substring(0, 16).replace("T", " ")
    } catch (_: Exception) {
        iso.take(16)
    }
}
