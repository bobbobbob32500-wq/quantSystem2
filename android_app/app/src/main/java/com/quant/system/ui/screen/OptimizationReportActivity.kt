package com.quant.system.ui.screen

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.core.test.OptimizationSummary
import com.quant.system.core.test.SummaryReport
import com.quant.system.ui.theme.QuantSystemTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class OptimizationReportActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            QuantSystemTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    OptimizationReportScreen()
                }
            }
        }
    }
}

@Composable
fun OptimizationReportScreen() {
    var summaryReport by remember { mutableStateOf<SummaryReport?>(null) }
    var isGeneratingReport by remember { mutableStateOf(false) }
    var isGeneratingHtml by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var reportFilePath by remember { mutableStateOf<String?>(null) }
    var htmlFilePath by remember { mutableStateOf<String?>(null) }
    
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    
    Scaffold(
        topBar = {
            Surface(
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "优化总结报告",
                        style = MaterialTheme.typography.headlineMedium,
                        color = MaterialTheme.colorScheme.onPrimary,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "移动应用性能优化效果总结",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.8f)
                    )
                }
            }
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(16.dp)
        ) {
            // 控制按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = {
                        isGeneratingReport = true
                        errorMessage = null
                        scope.launch {
                            try {
                                val report = withContext(Dispatchers.IO) {
                                    OptimizationSummary.generate(context)
                                }
                                summaryReport = report
                            } catch (e: Exception) {
                                errorMessage = "生成报告失败: ${e.message}"
                            } finally {
                                isGeneratingReport = false
                            }
                        }
                    },
                    enabled = !isGeneratingReport && !isGeneratingHtml,
                    modifier = Modifier.weight(1f)
                ) {
                    if (isGeneratingReport) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("生成中...")
                    } else {
                        Icon(
                            imageVector = Icons.Default.Assessment,
                            contentDescription = "生成报告",
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("生成优化报告")
                    }
                }
                
                Button(
                    onClick = {
                        isGeneratingHtml = true
                        errorMessage = null
                        scope.launch {
                            try {
                                val file = withContext(Dispatchers.IO) {
                                    OptimizationSummary.exportHtml(context)
                                }
                                htmlFilePath = file.absolutePath
                                
                                // 分享HTML文件
                                val shareIntent = Intent(Intent.ACTION_SEND).apply {
                                    type = "text/html"
                                    putExtra(Intent.EXTRA_STREAM, Uri.fromFile(file))
                                    putExtra(Intent.EXTRA_SUBJECT, "移动应用优化总结报告")
                                    putExtra(Intent.EXTRA_TEXT, "移动应用性能优化总结报告")
                                }
                                context.startActivity(Intent.createChooser(shareIntent, "分享优化报告"))
                            } catch (e: Exception) {
                                errorMessage = "生成HTML报告失败: ${e.message}"
                            } finally {
                                isGeneratingHtml = false
                            }
                        }
                    },
                    enabled = !isGeneratingReport && !isGeneratingHtml,
                    modifier = Modifier.weight(1f)
                ) {
                    if (isGeneratingHtml) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("生成中...")
                    } else {
                        Icon(
                            imageVector = Icons.Default.Download,
                            contentDescription = "导出HTML",
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("导出HTML报告")
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 错误消息
            errorMessage?.let { message ->
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Error,
                            contentDescription = "错误",
                            tint = MaterialTheme.colorScheme.error
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
            }
            
            // 文件路径
            htmlFilePath?.let { path ->
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer,
                        contentColor = MaterialTheme.colorScheme.onPrimaryContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.CheckCircle,
                            contentDescription = "成功",
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Column {
                            Text(
                                text = "HTML报告已生成",
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                text = path,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
            }
            
            // 报告内容
            summaryReport?.let { report ->
                ReportContentView(report = report)
            } ?: run {
                // 如果没有报告，显示提示
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.Info,
                            contentDescription = "信息",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(64.dp)
                        )
                        Spacer(modifier = Modifier.height(16.dp))
                        Text(
                            text = "点击上方按钮生成优化报告",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            text = "查看移动应用优化效果总结",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun ReportContentView(report: SummaryReport) {
    LazyColumn(
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // 总体概览
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "📊 总体概览",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(16.dp))
                    
                    // 统计信息
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        StatItem(
                            label = "组件验证",
                            value = "${report.verificationReport.passedComponents}/${report.verificationReport.totalComponents}",
                            color = MaterialTheme.colorScheme.primary
                        )
                        StatItem(
                            label = "验证成功率",
                            value = "${String.format("%.1f", report.verificationReport.successRate)}%",
                            color = if (report.verificationReport.successRate >= 90) Color(0xFF4CAF50) else Color(0xFFFF9800)
                        )
                        StatItem(
                            label = "指标达标",
                            value = "${report.validationResult.passedMetrics}/${report.validationResult.totalMetrics}",
                            color = if (report.validationResult.passRate >= 90) Color(0xFF4CAF50) else Color(0xFFFF9800)
                        )
                        StatItem(
                            label = "综合评分",
                            value = String.format("%.1f", report.performanceBenchmark.score),
                            color = when {
                                report.performanceBenchmark.score >= 90 -> Color(0xFF4CAF50)
                                report.performanceBenchmark.score >= 80 -> Color(0xFF8BC34A)
                                report.performanceBenchmark.score >= 70 -> Color(0xFFFFC107)
                                report.performanceBenchmark.score >= 60 -> Color(0xFFFF9800)
                                else -> Color(0xFFF44336)
                            }
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(16.dp))
                    
                    // 总体状态
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = when {
                                report.validationResult.overallStatus == "优秀" -> Color(0xFFE8F5E9)
                                report.validationResult.overallStatus == "良好" -> Color(0xFFE3F2FD)
                                report.validationResult.overallStatus == "中等" -> Color(0xFFFFF3E0)
                                else -> Color(0xFFFFEBEE)
                            }
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "总体状态",
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold
                                )
                                Text(
                                    text = report.validationResult.overallStatus,
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = when (report.validationResult.overallStatus) {
                                        "优秀" -> Color(0xFF2E7D32)
                                        "良好" -> Color(0xFF1565C0)
                                        "中等" -> Color(0xFFEF6C00)
                                        else -> Color(0xFFC62828)
                                    }
                                )
                            }
                            
                            Spacer(modifier = Modifier.height(8.dp))
                            
                            Text(
                                text = "优化措施实施完成度: ${String.format("%.1f", report.verificationReport.optimizationCoverage["总体"] ?: 0.0)}%",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            Text(
                                text = "性能基准评分: ${String.format("%.1f", report.performanceBenchmark.score)} (${report.performanceBenchmark.grade})",
                                style = MaterialTheme.typography.bodyMedium
                            )
                            Text(
                                text = "报告生成时间: ${report.formattedTimestamp}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }
        
        // 优化指标验证
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "🎯 优化指标验证",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    report.validationResult.results.forEach { metric ->
                        MetricValidationView(metric = metric)
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }
        }
        
        // 优化措施实施情况
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "🔧 优化措施实施情况",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    report.optimizationSummary.forEach { measure ->
                        OptimizationMeasureView(measure = measure)
                        Spacer(modifier = Modifier.height(12.dp))
                    }
                }
            }
        }
        
        // 优化建议
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "💡 优化建议",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    report.recommendations.forEach { recommendation ->
                        RecommendationView(recommendation = recommendation)
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }
        }
        
        // 性能基准测试结果
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        text = "📊 性能基准测试结果",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    // 网络性能
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp)
                        ) {
                            Text(
                                text = "网络性能",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            MetricRow(
                                label = "平均延迟",
                                value = "${String.format("%.1f", report.performanceBenchmark.networkLatency.averageLatency)}ms"
                            )
                            MetricRow(
                                label = "成功率",
                                value = "${String.format("%.1f", report.performanceBenchmark.networkLatency.successRate * 100)}%"
                            )
                            MetricRow(
                                label = "样本数",
                                value = report.performanceBenchmark.networkLatency.sampleCount.toString()
                            )
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // UI渲染性能
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp)
                        ) {
                            Text(
                                text = "UI渲染性能",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            MetricRow(
                                label = "平均帧时间",
                                value = "${String.format("%.1f", report.performanceBenchmark.uiRenderPerformance.averageFrameTime)}ms"
                            )
                            MetricRow(
                                label = "FPS",
                                value = String.format("%.1f", report.performanceBenchmark.uiRenderPerformance.fps)
                            )
                            MetricRow(
                                label = "卡顿率",
                                value = "${String.format("%.1f", report.performanceBenchmark.uiRenderPerformance.jankPercentage)}%"
                            )
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 内存使用
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp)
                        ) {
                            Text(
                                text = "内存使用",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            MetricRow(
                                label = "已用内存",
                                value = "${report.performanceBenchmark.memoryUsage.usedMemoryMB}MB"
                            )
                            MetricRow(
                                label = "总内存",
                                value = "${report.performanceBenchmark.memoryUsage.totalMemoryMB}MB"
                            )
                            MetricRow(
                                label = "使用率",
                                value = "${String.format("%.1f", report.performanceBenchmark.memoryUsage.memoryUsagePercentage)}%"
                            )
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 启动性能
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp)
                        ) {
                            Text(
                                text = "启动性能",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            MetricRow(
                                label = "启动时间",
                                value = "${report.performanceBenchmark.startupTime}ms"
                            )
                            MetricRow(
                                label = "测试耗时",
                                value = "${report.performanceBenchmark.totalDuration}ms"
                            )
                            MetricRow(
                                label = "综合评分",
                                value = String.format("%.1f", report.performanceBenchmark.score)
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun StatItem(label: String, value: String, color: Color) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = value,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            color = color
        )
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
fun MetricValidationView(metric: com.quant.system.core.test.MetricValidationResult) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (metric.passed) Color(0xFFE8F5E9) else Color(0xFFFFEBEE)
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = if (metric.passed) Icons.Default.CheckCircle else Icons.Default.Warning,
                contentDescription = if (metric.passed) "通过" else "未通过",
                tint = if (metric.passed) Color(0xFF4CAF50) else Color(0xFFF44336),
                modifier = Modifier.size(24.dp)
            )
            
            Spacer(modifier = Modifier.width(12.dp))
            
            Column(
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    text = metric.name,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold
                )
                
                Spacer(modifier = Modifier.height(4.dp))
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "当前: ${metric.formattedCurrent}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = "目标: ${metric.formattedTarget}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                
                Spacer(modifier = Modifier.height(4.dp))
                
                Text(
                    text = if (metric.passed) "✅ ${metric.status}" else "❌ ${metric.status}",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (metric.passed) Color(0xFF2E7D32) else Color(0xFFC62828)
                )
                
                if (!metric.passed) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = metric.improvement,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.sp
                    )
                }
            }
        }
    }
}

@Composable
fun OptimizationMeasureView(measure: com.quant.system.core.test.OptimizationMeasure) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = measure.category,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold
                )
                
                Text(
                    text = measure.status,
                    style = MaterialTheme.typography.bodySmall,
                    color = when (measure.status) {
                        "已实施" -> Color(0xFF4CAF50)
                        "进行中" -> Color(0xFFFF9800)
                        else -> Color(0xFF9E9E9E)
                    },
                    fontWeight = FontWeight.Bold
                )
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "实施措施:",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium
            )
            
            Spacer(modifier = Modifier.height(4.dp))
            
            measure.measures.forEach { item ->
                Text(
                    text = "• $item",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "预期收益:",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium
            )
            
            Spacer(modifier = Modifier.height(4.dp))
            
            measure.benefits.forEach { item ->
                Text(
                    text = "• $item",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF2E7D32),
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
        }
    }
}

@Composable
fun RecommendationView(recommendation: com.quant.system.core.test.FinalRecommendation) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = when (recommendation.priority) {
                "高" -> Color(0xFFFFEBEE)
                "中" -> Color(0xFFFFF3E0)
                else -> Color(0xFFE8F5E9)
            }
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = recommendation.area,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold
                )
                
                Text(
                    text = "${recommendation.priority}优先级",
                    style = MaterialTheme.typography.bodySmall,
                    color = when (recommendation.priority) {
                        "高" -> Color(0xFFD32F2F)
                        "中" -> Color(0xFFF57C00)
                        else -> Color(0xFF388E3C)
                    },
                    fontWeight = FontWeight.Bold
                )
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "问题: ${recommendation.issue}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            Spacer(modifier = Modifier.height(4.dp))
            
            Text(
                text = "建议: ${recommendation.suggestion}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            Spacer(modifier = Modifier.height(4.dp))
            
            Text(
                text = "预期影响: ${recommendation.expectedImpact}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun MetricRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium
        )
    }
}