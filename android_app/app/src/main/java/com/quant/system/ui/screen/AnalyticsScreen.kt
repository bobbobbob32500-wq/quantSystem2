package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.AnalyticsSummaryPayload
import com.quant.system.ui.screen.viewmodel.NoticeType

@Composable
fun AnalyticsScreen(
    summary: AnalyticsSummaryPayload?,
    message: String?,
    noticeType: NoticeType,
    onRefresh: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(
                title = "复盘统计",
                subtitle = "查看周/月命中率与策略表现摘要。",
            )
        }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
        }
        item {
            DetailCard(
                title = "核心指标",
                lines = listOf(
                    "周命中率：${"%.2f".format(summary?.weekHitRate ?: 0.0)}%",
                    "月命中率：${"%.2f".format(summary?.monthHitRate ?: 0.0)}%",
                    "策略成功率：${"%.2f".format(summary?.strategySuccessRate ?: 0.0)}%",
                    "最近推荐日：${summary?.latestRecommendationDate ?: "--"}",
                ),
            )
        }
        item {
            DetailCard(
                title = "收益摘要",
                lines = listOf(
                    "平均净收益：${summary?.returnSummary?.get("mean_net_return_pct") ?: "--"}",
                    "平均最大有利：${summary?.returnSummary?.get("mean_mfe_pct") ?: "--"}",
                    "平均最大不利：${summary?.returnSummary?.get("mean_mae_pct") ?: "--"}",
                ),
            )
        }
        item {
            PrimaryButton(
                text = "刷新统计",
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (summary == null) {
            item { EmptyStateCard("暂无统计数据，请稍后重试。") }
        } else {
            item { Text("统计已同步", modifier = Modifier.padding(bottom = 20.dp)) }
        }
    }
}
