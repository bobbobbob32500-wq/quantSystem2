package com.quant.system.ui.screen

import androidx.compose.foundation.background
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
import com.quant.system.data.model.MistakeItem
import com.quant.system.data.model.SuccessPattern
import com.quant.system.data.model.ImprovementPlan
import com.quant.system.data.model.DeepReviewResult

@Composable
fun DeepReviewScreen(
    result: DeepReviewResult?,
    onRefresh: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(title = "深度复盘", subtitle = "错误识别、经验提炼、改进计划")
        }

        if (result == null) {
            item {
                EmptyStateCard("暂无复盘数据，请先执行交易后复盘")
            }
            item {
                PrimaryButton(text = "执行深度复盘", onClick = onRefresh, modifier = Modifier.fillMaxWidth())
            }
            return@LazyColumn
        }

        // 错误操作
        if (result.mistakes.isNotEmpty()) {
            item {
                SectionTitle("错误操作识别", Color(0xFFDC2626))
            }
            items(result.mistakes) { mistake ->
                MistakeCard(mistake)
            }
        }

        // 成功模式
        if (result.successPatterns.isNotEmpty()) {
            item {
                SectionTitle("成功模式提炼", Color(0xFF22C55E))
            }
            items(result.successPatterns) { pattern ->
                SuccessPatternCard(pattern)
            }
        }

        // 改进计划
        val plan = result.improvementPlan
        if (plan != null) {
            item {
                SectionTitle("改进计划", Color(0xFF6366F1))
            }
            item {
                ImprovementPlanCard(plan)
            }
        }

        item {
            SecondaryButton(text = "重新复盘", onClick = onRefresh, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun SectionTitle(title: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(modifier = Modifier.size(8.dp).background(color, androidx.compose.foundation.shape.RoundedCornerShape(4.dp)))
        Spacer(modifier = Modifier.width(8.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun MistakeCard(mistake: MistakeItem) {
    Card {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(mistake.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(mistake.severity, fontSize = 11.sp, color = if (mistake.severity == "high") Color.Red else Color.Gray)
            }
            Text(mistake.lesson, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF6366F1))
        }
    }
}

@Composable
private fun SuccessPatternCard(pattern: SuccessPattern) {
    Card {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(pattern.pattern, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("次数: ${pattern.count}", fontSize = 12.sp, color = Color.Gray)
                Text("胜率: ${(pattern.winRate * 100).toInt()}%", fontSize = 12.sp, color = Color(0xFF22C55E))
                Text("均收: ${pattern.avgReturnPct}%", fontSize = 12.sp, color = Color.Gray)
            }
            Text(pattern.suggestion, fontSize = 12.sp, color = Color(0xFF6366F1))
        }
    }
}

@Composable
private fun ImprovementPlanCard(plan: ImprovementPlan) {
    Card {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(plan.overallAssessment, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)

            if (plan.improvements.isNotEmpty()) {
                Text("改进措施:", fontSize = 13.sp, fontWeight = FontWeight.Medium)
                plan.improvements.forEach { improvement ->
                    Row(modifier = Modifier.padding(start = 8.dp)) {
                        Text("• ", fontSize = 12.sp)
                        Text(improvement, fontSize = 12.sp)
                    }
                }
            }

            if (plan.priorities.isNotEmpty()) {
                Text("优先级:", fontSize = 13.sp, fontWeight = FontWeight.Medium)
                plan.priorities.sortedBy { it.priority }.forEach { priority ->
                    Row(modifier = Modifier.padding(start = 8.dp)) {
                        Text("P${priority.priority}: ", fontSize = 12.sp, fontWeight = FontWeight.Medium)
                        Text(priority.action, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
