package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.SignalItem
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class DecisionStep(
    val index: String,
    val title: String,
    val detail: String,
    val tag: String,
    val tone: PillTone,
    val deadline: String,
)

private data class PrismInsight(
    val label: String,
    val value: String,
    val detail: String,
    val chip: String? = null,
    val tone: PillTone = PillTone.Neutral,
)

private data class IntelEntry(
    val title: String,
    val detail: String,
    val tag: String,
    val tone: PillTone,
)

@Composable
fun OverviewScreen(
    snapshot: DashboardSnapshot?,
    isLoading: Boolean,
    isActionRunning: Boolean,
    runningAction: String?,
    message: String?,
    noticeType: NoticeType,
    autoRefreshSecondsRemaining: Int,
    lastSyncedAtLabel: String?,
    dataSourceLabel: String,
    networkStatusLabel: String,
    isUsingCachedData: Boolean,
    onRefresh: () -> Unit,
    onRunStockSelection: () -> Unit,
    onGeneratePlan: () -> Unit,
    onOpenActions: () -> Unit,
    onNavigateToCandidates: () -> Unit,
    onNavigateToTrades: () -> Unit,
) {
    val candidateCount = snapshot?.candidatePool?.count ?: snapshot?.candidatePool?.topCandidates?.size ?: 0
    val signalCount = snapshot?.signals?.recentCount ?: snapshot?.signals?.latestItems?.size ?: 0
    val tradeCount = snapshot?.virtualTrades?.openCount ?: snapshot?.virtualTrades?.openTrades?.size ?: 0
    val topCandidate = snapshot?.candidatePool?.topCandidates?.maxByOrNull { it.score ?: Double.MIN_VALUE }
    val latestSignal = snapshot?.signals?.latestItems?.firstOrNull()
    val heroSubtitle = if (isActionRunning) {
        "动作执行中，自动刷新暂时暂停"
    } else {
        "${autoRefreshSecondsRemaining}s 后刷新 · 最近同步 ${lastSyncedAtLabel ?: "--"}"
    }
    val decisionSteps = remember(topCandidate, latestSignal, snapshot) {
        listOf(
            DecisionStep(
                index = "01",
                title = "先复核超时卖点，不先做新开仓",
                detail = latestSignal?.triggerReason?.takeIf { it.isNotBlank() }
                    ?: "当前最危险的不是错过机会，而是把策略正常退出误判成异常清仓。",
                tag = "最高优先",
                tone = PillTone.Negative,
                deadline = "立即",
            ),
            DecisionStep(
                index = "02",
                title = "确认首页唯一重点候选",
                detail = topCandidate?.let {
                    "${it.name.orDash()} ${candidateSymbol(it).orDash()} 当前评分 ${formatScore(it.score)}，适合作为首页唯一重点候选。"
                } ?: "候选分数、结构和风险领先的标的应该成为首页唯一重点，而不是和普通候选并列展示。",
                tag = "候选主线",
                tone = PillTone.Positive,
                deadline = "候选确认",
            ),
            DecisionStep(
                index = "03",
                title = "最后再生成尾盘计划",
                detail = "计划应该基于已经确认过的候选、卖点和持仓上下文，而不是先生成再返工。",
                tag = "收束动作",
                tone = PillTone.Neutral,
                deadline = "尾盘前",
            ),
        )
    }
    val prismInsights = remember(snapshot) {
        listOf(
            PrismInsight(
                label = "强度",
                value = snapshot?.todayBoard?.status?.takeIf { it.isNotBlank() } ?: "偏强",
                detail = snapshot?.meta?.marketSession?.detail?.takeIf { it.isNotBlank() }
                    ?: "突破和二次启动同时活跃，但龙头聚焦度更高。",
            ),
            PrismInsight(
                label = "风险",
                value = snapshot?.health?.statusLabel?.takeIf { it.isNotBlank() } ?: "可控",
                detail = snapshot?.todayBoard?.reason?.takeIf { it.isNotBlank() }
                    ?: "主要风险来自策略退出解释，不来自系统链路异常。",
                chip = "解释优先",
                tone = PillTone.Negative,
            ),
            PrismInsight(
                label = "窗口",
                value = snapshot?.meta?.marketSession?.phase?.takeIf { it.isNotBlank() } ?: "尾盘前",
                detail = "今天更适合做收束判断，不适合盲目扩张仓位。",
                chip = "收束时段",
                tone = PillTone.Neutral,
            ),
        )
    }
    val intelEntries = remember(topCandidate, latestSignal, snapshot) {
        listOf(
            IntelEntry(
                title = topCandidate?.let { "${it.name.orDash()} ${candidateSymbol(it).orDash()}" } ?: "候选主线待确认",
                detail = topCandidate?.triggerReason?.takeIf { it.isNotBlank() }
                    ?: "二次启动评分最高，结构完整，适合作为首页唯一重点候选。",
                tag = topCandidate?.score?.let(::formatScore) ?: "--",
                tone = PillTone.Positive,
            ),
            IntelEntry(
                title = latestSignal?.let { "${it.name.orDash()} ${signalSymbol(it).orDash()}" } ?: "卖点待复核",
                detail = latestSignal?.triggerReason?.takeIf { it.isNotBlank() }
                    ?: "第一步不是直接执行卖出，而是确认退出规则、持仓映射和策略参数版本是否一致。",
                tag = latestSignal?.signalType?.takeIf { it.isNotBlank() } ?: "信号",
                tone = signalTone(latestSignal?.signalType),
            ),
            IntelEntry(
                title = "AI 管家摘要",
                detail = snapshot?.todayBoard?.reason?.takeIf { it.isNotBlank() }
                    ?: "当前更像策略卖点集中触发，不像系统异常清仓；建议先查参数映射，而不是立即反向操作。",
                tag = "AI",
                tone = PillTone.Neutral,
            ),
        )
    }

    RefreshContainer(isRefreshing = isLoading, onRefresh = onRefresh) {
        LazyColumn(
            modifier = Modifier.padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (!message.isNullOrBlank()) {
                item { NoticeBanner(message = message, type = noticeType, onRetry = onRefresh) }
            }

            if (isLoading && snapshot == null) {
                items(5) { LoadingSkeletonCard(lines = 4) }
                return@LazyColumn
            }

            item {
                HeroSection(
                    title = snapshot?.todayBoard?.action?.takeIf { it.isNotBlank() } ?: "市场状态",
                    value = snapshot?.todayBoard?.status?.takeIf { it.isNotBlank() } ?: "系统运行中",
                    subtitle = heroSubtitle,
                    percentage = snapshot?.health?.statusLabel?.takeIf { it.isNotBlank() },
                    isPositive = snapshot?.health?.status == "healthy",
                    stats = listOf(
                        Triple("候选", candidateCount.toString(), ""),
                        Triple("信号", signalCount.toString(), ""),
                        Triple("持仓", tradeCount.toString(), ""),
                    ),
                )
            }

            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    StatusPill(
                        text = "数据源：$dataSourceLabel",
                        tone = if (isUsingCachedData) PillTone.Neutral else PillTone.Positive,
                    )
                    StatusPill(
                        text = networkStatusLabel,
                        tone = when {
                            networkStatusLabel.contains("正常") -> PillTone.Positive
                            networkStatusLabel.contains("慢") -> PillTone.Neutral
                            else -> PillTone.Negative
                        },
                    )
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    SummaryMiniCard(
                        title = "候选池",
                        value = candidateCount.toString(),
                        detail = "进入候选页继续筛选与推送",
                        modifier = Modifier.weight(1f),
                    )
                    SummaryMiniCard(
                        title = "持仓",
                        value = tradeCount.toString(),
                        detail = "查看按策略分组的只读账本",
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    SecondaryButton(
                        text = "候选池",
                        onClick = onNavigateToCandidates,
                        modifier = Modifier.weight(1f),
                    )
                    SecondaryButton(
                        text = "动作中心",
                        onClick = onOpenActions,
                        modifier = Modifier.weight(1f),
                    )
                    SecondaryButton(
                        text = "持仓",
                        onClick = onNavigateToTrades,
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            item {
                DecisionSheetCard(
                    steps = decisionSteps,
                    isActionRunning = isActionRunning,
                    runningAction = runningAction,
                    onRunStockSelection = onRunStockSelection,
                    onGeneratePlan = onGeneratePlan,
                )
            }

            item {
                PrismInsightsCard(insights = prismInsights)
            }

            item {
                IntelBoardCard(entries = intelEntries)
            }

            item {
                HealthCard(
                    status = snapshot?.health?.statusLabel ?: "未知",
                    subtitle = snapshot?.health?.subtitle ?: "暂无健康快照",
                    isHealthy = snapshot?.health?.status == "healthy",
                )
            }
        }
    }
}

@Composable
private fun DecisionSheetCard(
    steps: List<DecisionStep>,
    isActionRunning: Boolean,
    runningAction: String?,
    onRunStockSelection: () -> Unit,
    onGeneratePlan: () -> Unit,
) {
    val runSelectionLoading = isActionRunning && runningAction == "run_stock_selection"
    val generatePlanLoading = isActionRunning && runningAction == "generate_plan"

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
                text = "决策序列",
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "首页不是入口合集，而是动作顺序。",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            steps.forEach { step ->
                DecisionStepCard(step)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PrimaryButton(
                    text = if (runSelectionLoading) "执行中..." else "执行选股",
                    onClick = onRunStockSelection,
                    modifier = Modifier.weight(1f),
                    enabled = !isActionRunning,
                )
                SecondaryButton(
                    text = if (generatePlanLoading) "生成中..." else "生成计划",
                    onClick = onGeneratePlan,
                    modifier = Modifier.weight(1f),
                    enabled = !isActionRunning,
                )
            }
        }
    }
}

@Composable
private fun DecisionStepCard(step: DecisionStep) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "${step.index} ${step.title}。${step.detail}" },
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.6f)),
        shape = RoundedCornerShape(20.dp),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier = Modifier
                    .size(42.dp)
                    .background(color = Color.White.copy(alpha = 0.9f), shape = RoundedCornerShape(14.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Text(step.index, color = TextPrimary, fontWeight = FontWeight.Bold)
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = step.title,
                    style = MaterialTheme.typography.titleSmall,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = step.detail,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                StatusPill(text = step.tag, tone = step.tone)
                Text(
                    text = step.deadline,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary,
                )
            }
        }
    }
}

@Composable
private fun PrismInsightsCard(insights: List<PrismInsight>) {
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
                text = "市场棱镜",
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "用三块判断替代普通信息流。",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                insights.forEach { insight ->
                    Card(
                        modifier = Modifier.weight(1f),
                        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.55f)),
                        shape = RoundedCornerShape(20.dp),
                    ) {
                        Column(
                            modifier = Modifier.padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(
                                text = insight.label,
                                style = MaterialTheme.typography.labelSmall,
                                color = TextSecondary,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                text = insight.value,
                                style = MaterialTheme.typography.titleMedium,
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                            )
                            insight.chip?.let {
                                StatusPill(text = it, tone = insight.tone)
                            }
                            Text(
                                text = insight.detail,
                                style = MaterialTheme.typography.bodySmall,
                                color = TextSecondary,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun IntelBoardCard(entries: List<IntelEntry>) {
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
                text = "关键情报",
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "只保留会改变动作判断的内容。",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary,
            )
            entries.forEach { entry ->
                IntelCard(entry)
            }
        }
    }
}

@Composable
private fun IntelCard(entry: IntelEntry) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
        shape = RoundedCornerShape(20.dp),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    text = entry.title,
                    style = MaterialTheme.typography.titleSmall,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = entry.detail,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            StatusPill(text = entry.tag, tone = entry.tone)
        }
    }
}

@Composable
private fun SummaryMiniCard(
    title: String,
    value: String,
    detail: String,
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
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(text = title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(text = value, style = MaterialTheme.typography.headlineSmall, color = TextPrimary, fontWeight = FontWeight.Bold)
            Text(text = detail, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

private fun candidateSymbol(candidate: Candidate): String? =
    candidate.symbol?.trim()?.takeIf { it.isNotBlank() }
        ?: candidate.tsCode?.substringBefore(".")?.trim()?.takeIf { it.isNotBlank() }

private fun signalSymbol(signal: SignalItem): String? =
    signal.tsCode?.substringBefore(".")?.trim()?.takeIf { it.isNotBlank() }

private fun formatScore(score: Double?): String = score?.let { "%.1f".format(it) } ?: "--"

private fun signalTone(signalType: String?): PillTone {
    val normalized = signalType?.lowercase().orEmpty()
    return when {
        normalized.contains("sell") || normalized.contains("卖") -> PillTone.Negative
        normalized.contains("buy") || normalized.contains("买") -> PillTone.Positive
        else -> PillTone.Neutral
    }
}

private fun String?.orDash(): String = this?.takeIf { it.isNotBlank() } ?: "--"
