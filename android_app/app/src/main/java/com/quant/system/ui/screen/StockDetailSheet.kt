package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.StockDetailPayload

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StockDetailSheet(
    detail: StockDetailPayload,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(text = "${detail.name ?: "--"} (${detail.symbol})")
            detail.marketPhase?.takeIf { it.isNotBlank() }?.let {
                DetailCard(title = "市场阶段", lines = listOf(it))
            }
            detail.selectionReason?.takeIf { it.isNotBlank() }?.let {
                DetailCard(title = "入选原因", lines = listOf(it))
            }
            DetailCard(
                title = "策略标签",
                lines = if (detail.strategyTags.isEmpty()) listOf("--") else detail.strategyTags,
            )
            val risks = (detail.keyRisks + detail.riskTags).distinct().ifEmpty { listOf("风险可控") }
            DetailCard(title = "关键风险项", lines = risks)
            DetailCard(
                title = "建议动作",
                lines = listOf(detail.actionSuggestion ?: "等待下一次信号确认"),
            )
            if (detail.todoActions.isNotEmpty()) {
                DetailCard(title = "待办清单", lines = detail.todoActions)
            }
            if (detail.signalTimeline.isNotEmpty()) {
                DetailCard(
                    title = "信号时间线",
                    lines = detail.signalTimeline.take(8).mapIndexed { index, signal ->
                        val tsCode = signal["ts_code"]?.toString()?.replace("\"", "") ?: "--"
                        val signalType = signal["signal_type"]?.toString()?.replace("\"", "") ?: "--"
                        val signalTime = signal["signal_time"]?.toString()?.replace("\"", "") ?: "--"
                        "${index + 1}. $tsCode · $signalType · $signalTime"
                    },
                )
            }
        }
    }
}
