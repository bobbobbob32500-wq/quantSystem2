package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

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
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            TopBar(
                title = "策略中心",
                subtitle = "查看策略说明、适用场景和默认参数，并从这里直接发起运行。",
                eyebrow = "Strategy Desk",
            )
        }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
        }

        item {
            HeroSection(
                title = "策略面板",
                value = strategyItems.size.toString(),
                subtitle = "先设定参数，再挑策略运行。",
                stats = listOf(
                    Triple("TopK", topKInput, ""),
                    Triple("最低分", minScoreInput, ""),
                    Triple("可用策略", strategyItems.size.toString(), ""),
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
                        text = "运行参数",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = topKInput,
                            onValueChange = { topKInput = it },
                            label = { Text("TopK") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            shape = RoundedCornerShape(18.dp),
                        )
                        OutlinedTextField(
                            value = minScoreInput,
                            onValueChange = { minScoreInput = it },
                            label = { Text("最小评分") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            shape = RoundedCornerShape(18.dp),
                        )
                    }
                    SecondaryButton(
                        text = "刷新策略列表",
                        onClick = onRefresh,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        if (strategyItems.isEmpty()) {
            item { EmptyStateCard("暂无策略，请检查后端接口或稍后重试。") }
        } else {
            item {
                DetailCard(
                    title = "策略摘要",
                    lines = strategyItems.map { item ->
                        "${item.name} · 场景：${item.scene ?: "--"}"
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = strategy.name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = TextPrimary,
            )
            strategy.description?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StrategyMetaChip(label = "适用场景", value = strategy.scene ?: "--", modifier = Modifier.weight(1f))
                StrategyMetaChip(label = "默认参数", value = strategy.defaultParams?.toString() ?: "{}", modifier = Modifier.weight(1f))
            }
            PrimaryButton(
                text = "运行策略",
                onClick = onRun,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun StrategyMetaChip(
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
            Text(text = value, style = MaterialTheme.typography.bodySmall, color = TextPrimary, fontWeight = FontWeight.SemiBold)
        }
    }
}
