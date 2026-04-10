package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.StrategyMeta
import com.quant.system.ui.screen.viewmodel.NoticeType

@Composable
fun StrategyCenterScreen(
    strategies: List<StrategyMeta>,
    message: String?,
    noticeType: NoticeType,
    onRefresh: () -> Unit,
    onRunStrategy: (String, Map<String, Any?>) -> Unit,
) {
    var topKInput by rememberSaveable { mutableStateOf("15") }
    var minScoreInput by rememberSaveable { mutableStateOf("60") }
    val strategyItems = remember(strategies) { strategies }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(
                title = "策略中心",
                subtitle = "查看策略说明、适用场景和基础参数",
            )
        }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = topKInput,
                    onValueChange = { topKInput = it },
                    label = { Text("TopK") },
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
                OutlinedTextField(
                    value = minScoreInput,
                    onValueChange = { minScoreInput = it },
                    label = { Text("最小评分") },
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
            }
        }
        item {
            OutlinedButtonCompat(
                text = "刷新策略列表",
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (strategyItems.isEmpty()) {
            item { EmptyStateCard("暂无策略，请检查后端接口或稍后重试") }
        } else {
            item {
                DetailCard(
                    title = "策略结果摘要对比",
                    lines = strategyItems.map { item ->
                        "${item.name} · 场景：${item.scene ?: "--"} · 默认参数：${item.defaultParams ?: "{}"}"
                    },
                )
            }
            items(strategyItems, key = { it.id }) { strategy ->
                StrategyCard(
                    strategy = strategy,
                    onRun = {
                        val params = mapOf(
                            "top_k" to (topKInput.toIntOrNull() ?: 15),
                            "min_score" to (minScoreInput.toDoubleOrNull() ?: 60.0),
                        )
                        onRunStrategy(strategy.id, params)
                    },
                )
            }
        }
    }
}

@Composable
private fun StrategyCard(
    strategy: StrategyMeta,
    onRun: () -> Unit,
) {
    Card(colors = CardDefaults.cardColors()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = strategy.name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = strategy.description ?: "--",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                text = "适用场景：${strategy.scene ?: "--"}",
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                text = "默认参数：${strategy.defaultParams ?: "{}"}",
                style = MaterialTheme.typography.bodySmall,
            )
            PrimaryButton(
                text = "运行策略",
                onClick = onRun,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun OutlinedButtonCompat(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    SecondaryButton(text = text, onClick = onClick, modifier = modifier)
}
