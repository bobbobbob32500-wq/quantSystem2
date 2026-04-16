package com.quant.system.ui.screen

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
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
import com.quant.system.core.test.OptimizationTestSuite
import com.quant.system.core.test.PerformanceBenchmark
import com.quant.system.core.test.TestReport
import com.quant.system.core.test.TestResult
import com.quant.system.core.test.TestStatus
import com.quant.system.ui.theme.QuantSystemTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class OptimizationTestActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            QuantSystemTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    OptimizationTestScreen()
                }
            }
        }
    }
}

@Composable
fun OptimizationTestScreen() {
    var testReport by remember { mutableStateOf<TestReport?>(null) }
    var performanceBenchmark by remember { mutableStateOf<PerformanceBenchmark?>(null) }
    var isRunningTests by remember { mutableStateOf(false) }
    var isRunningBenchmark by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var exportPath by remember { mutableStateOf<String?>(null) }
    
    val scope = rememberCoroutineScope()
    val appContext = LocalContext.current.applicationContext

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
                        text = "优化测试套件",
                        style = MaterialTheme.typography.headlineMedium,
                        color = MaterialTheme.colorScheme.onPrimary,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "验证移动应用性能优化效果",
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
                        isRunningTests = true
                        errorMessage = null
                        scope.launch {
                            try {
                                val report = withContext(Dispatchers.IO) {
                                    OptimizationTestSuite.runTests(appContext)
                                }
                                testReport = report
                            } catch (e: Exception) {
                                errorMessage = "测试运行失败: ${e.message}"
                            } finally {
                                isRunningTests = false
                            }
                        }
                    },
                    enabled = !isRunningTests && !isRunningBenchmark,
                    modifier = Modifier.weight(1f)
                ) {
                    if (isRunningTests) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("运行中...")
                    } else {
                        Icon(
                            imageVector = Icons.Default.PlayArrow,
                            contentDescription = "运行测试",
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("运行优化测试")
                    }
                }
                
                Button(
                    onClick = {
                        isRunningBenchmark = true
                        errorMessage = null
                        scope.launch {
                            try {
                                val benchmark = withContext(Dispatchers.IO) {
                                    OptimizationTestSuite.runBenchmark(appContext)
                                }
                                performanceBenchmark = benchmark
                            } catch (e: Exception) {
                                errorMessage = "基准测试运行失败: ${e.message}"
                            } finally {
                                isRunningBenchmark = false
                            }
                        }
                    },
                    enabled = !isRunningTests && !isRunningBenchmark,
                    modifier = Modifier.weight(1f)
                ) {
                    if (isRunningBenchmark) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("测试中...")
                    } else {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "运行基准测试",
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("性能基准测试")
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
            
            // 导出路径
            exportPath?.let { path ->
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
                                text = "报告已导出",
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
            
            // 测试报告
            testReport?.let { report ->
                TestReportView(report = report)
            }
            
            // 性能基准测试结果
            performanceBenchmark?.let { benchmark ->
                PerformanceBenchmarkView(benchmark = benchmark)
            }
            
            // 如果没有数据，显示提示
            if (testReport == null && performanceBenchmark == null && errorMessage == null) {
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
                            text = "点击上方按钮运行测试",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            text = "验证移动应用优化效果",
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
fun TestReportView(report: TestReport) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // 标题
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "优化测试报告",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = report.formattedTimestamp,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 摘要
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        TestMetricItem(
                            label = "总测试数",
                            value = report.totalTests.toString(),
                            color = MaterialTheme.colorScheme.primary
                        )
                        TestMetricItem(
                            label = "通过",
                            value = report.passedTests.toString(),
                            color = Color(0xFF4CAF50) // 绿色
                        )
                        TestMetricItem(
                            label = "失败",
                            value = report.failedTests.toString(),
                            color = Color(0xFFF44336) // 红色
                        )
                        TestMetricItem(
                            label = "跳过",
                            value = report.skippedTests.toString(),
                            color = Color(0xFF9E9E9E) // 灰色
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    // 成功率
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "成功率",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f)
                        )
                        Text(
                            text = "${String.format("%.1f", report.successRate)}%",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = when {
                                report.successRate >= 90 -> Color(0xFF4CAF50) // 绿色
                                report.successRate >= 70 -> Color(0xFFFF9800) // 橙色
                                else -> Color(0xFFF44336) // 红色
                            }
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    LinearProgressIndicator(
                        progress = { (report.successRate / 100).toFloat() },
                        modifier = Modifier.fillMaxWidth(),
                        color = when {
                            report.successRate >= 90 -> Color(0xFF4CAF50) // 绿色
                            report.successRate >= 70 -> Color(0xFFFF9800) // 橙色
                            else -> Color(0xFFF44336) // 红色
                        },
                        trackColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 按类别显示结果
            Text(
                text = "测试结果",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                report.resultsByCategory.forEach { (category, results) ->
                    item {
                        CategoryResultsView(category = category, results = results)
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 优化建议
            if (report.recommendations.isNotEmpty()) {
                Text(
                    text = "优化建议",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                
                Spacer(modifier = Modifier.height(8.dp))
                
                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(report.recommendations) { recommendation ->
                        RecommendationView(recommendation = recommendation)
                    }
                }
            }
        }
    }
}

@Composable
fun TestMetricItem(label: String, value: String, color: Color) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = value,
            style = MaterialTheme.typography.titleMedium,
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
fun CategoryResultsView(category: String, results: List<TestResult>) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            // 类别标题
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = category,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f)
                )
                
                val passedCount = results.count { it.status == TestStatus.PASSED }
                val totalCount = results.size
                Text(
                    text = "$passedCount/$totalCount",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (passedCount == totalCount) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // 测试结果
            Column(
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                results.forEach { result ->
                    TestResultView(result = result)
                }
            }
        }
    }
}

@Composable
fun TestResultView(result: TestResult) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 状态图标
        Icon(
            imageVector = when (result.status) {
                TestStatus.PASSED -> Icons.Default.CheckCircle
                TestStatus.FAILED -> Icons.Default.Error
                TestStatus.SKIPPED -> Icons.Default.Info
            },
            contentDescription = result.status.name,
            tint = when (result.status) {
                TestStatus.PASSED -> Color(0xFF4CAF50) // 绿色
                TestStatus.FAILED -> Color(0xFFF44336) // 红色
                TestStatus.SKIPPED -> Color(0xFF9E9E9E) // 灰色
            },
            modifier = Modifier.size(16.dp)
        )
        
        Spacer(modifier = Modifier.width(8.dp))
        
        // 测试名称和描述
        Column(
            modifier = Modifier.weight(1f)
        ) {
            Text(
                text = result.testName,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium
            )
            Text(
                text = result.description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            // 详细信息
            if (result.details.isNotBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = result.details,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                    fontSize = 12.sp
                )
            }
        }
    }
}

@Composable
fun RecommendationView(recommendation: com.quant.system.core.test.Recommendation) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = when (recommendation.priority) {
                "高" -> Color(0xFFFFEBEE) // 浅红色
                "中" -> Color(0xFFFFF3E0) // 浅橙色
                else -> Color(0xFFE8F5E9) // 浅绿色
            },
            contentColor = when (recommendation.priority) {
                "高" -> Color(0xFFC62828) // 深红色
                "中" -> Color(0xFFEF6C00) // 深橙色
                else -> Color(0xFF2E7D32) // 深绿色
            }
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            // 优先级标签
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = recommendation.category,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold
                )
                
                Text(
                    text = "${recommendation.priority}优先级",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Bold,
                    color = when (recommendation.priority) {
                        "高" -> Color(0xFFD32F2F)
                        "中" -> Color(0xFFF57C00)
                        else -> Color(0xFF388E3C)
                    }
                )
            }
            
            Spacer(modifier = Modifier.height(4.dp))
            
            // 描述
            Text(
                text = recommendation.description,
                style = MaterialTheme.typography.bodyMedium
            )
            
            Spacer(modifier = Modifier.height(4.dp))
            
            // 建议
            Text(
                text = "建议: ${recommendation.suggestion}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            Spacer(modifier = Modifier.height(2.dp))
            
            // 影响
            Text(
                text = "影响: ${recommendation.impact}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun PerformanceBenchmarkView(benchmark: PerformanceBenchmark) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // 标题
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "性能基准测试",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = benchmark.formattedTimestamp,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 综合评分
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "综合性能评分",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 评分圆环
                    Box(
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(
                            progress = { (benchmark.score / 100).toFloat() },
                            modifier = Modifier.size(120.dp),
                            strokeWidth = 8.dp,
                            color = when {
                                benchmark.score >= 90 -> Color(0xFF4CAF50) // 绿色
                                benchmark.score >= 80 -> Color(0xFF8BC34A) // 浅绿
                                benchmark.score >= 70 -> Color(0xFFFFC107) // 黄色
                                benchmark.score >= 60 -> Color(0xFFFF9800) // 橙色
                                else -> Color(0xFFF44336) // 红色
                            },
                            trackColor = MaterialTheme.colorScheme.surfaceVariant
                        )
                        
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                text = "${benchmark.score.toInt()}",
                                style = MaterialTheme.typography.headlineLarge,
                                fontWeight = FontWeight.Bold,
                                color = when {
                                    benchmark.score >= 90 -> Color(0xFF4CAF50)
                                    benchmark.score >= 80 -> Color(0xFF8BC34A)
                                    benchmark.score >= 70 -> Color(0xFFFFC107)
                                    benchmark.score >= 60 -> Color(0xFFFF9800)
                                    else -> Color(0xFFF44336)
                                }
                            )
                            Text(
                                text = benchmark.grade,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(16.dp))
                    
                    // 测试耗时
                    Text(
                        text = "测试耗时: ${benchmark.totalDuration}ms",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 详细指标
            Text(
                text = "详细指标",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // 网络延迟
            BenchmarkMetricItem(
                label = "网络延迟",
                value = "${String.format("%.1f", benchmark.networkLatency.averageLatency)}ms",
                description = "平均请求延迟",
                color = when {
                    benchmark.networkLatency.averageLatency < 100 -> Color(0xFF4CAF50)
                    benchmark.networkLatency.averageLatency < 300 -> Color(0xFFFFC107)
                    else -> Color(0xFFF44336)
                }
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // UI渲染性能
            BenchmarkMetricItem(
                label = "UI渲染性能",
                value = "${String.format("%.1f", benchmark.uiRenderPerformance.averageFrameTime)}ms",
                description = "平均帧时间 (${String.format("%.0f", benchmark.uiRenderPerformance.fps)} FPS)",
                color = when {
                    benchmark.uiRenderPerformance.averageFrameTime < 16.7 -> Color(0xFF4CAF50)
                    benchmark.uiRenderPerformance.averageFrameTime < 33.3 -> Color(0xFFFFC107)
                    else -> Color(0xFFF44336)
                }
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // 内存使用
            BenchmarkMetricItem(
                label = "内存使用",
                value = "${String.format("%.1f", benchmark.memoryUsage.memoryUsagePercentage)}%",
                description = "${benchmark.memoryUsage.usedMemoryMB}MB / ${benchmark.memoryUsage.totalMemoryMB}MB",
                color = when {
                    benchmark.memoryUsage.memoryUsagePercentage < 70 -> Color(0xFF4CAF50)
                    benchmark.memoryUsage.memoryUsagePercentage < 85 -> Color(0xFFFFC107)
                    else -> Color(0xFFF44336)
                }
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // 启动时间
            BenchmarkMetricItem(
                label = "启动时间",
                value = "${benchmark.startupTime}ms",
                description = "应用启动时间",
                color = when {
                    benchmark.startupTime < 1000 -> Color(0xFF4CAF50)
                    benchmark.startupTime < 2000 -> Color(0xFFFFC107)
                    else -> Color(0xFFF44336)
                }
            )
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 网络延迟详情
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
                        text = "网络延迟详情",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        BenchmarkDetailItem(
                            label = "最低",
                            value = "${String.format("%.1f", benchmark.networkLatency.minLatency)}ms"
                        )
                        BenchmarkDetailItem(
                            label = "平均",
                            value = "${String.format("%.1f", benchmark.networkLatency.averageLatency)}ms"
                        )
                        BenchmarkDetailItem(
                            label = "最高",
                            value = "${String.format("%.1f", benchmark.networkLatency.maxLatency)}ms"
                        )
                        BenchmarkDetailItem(
                            label = "成功率",
                            value = "${String.format("%.1f", benchmark.networkLatency.successRate * 100)}%"
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(4.dp))
                    
                    Text(
                        text = "样本数: ${benchmark.networkLatency.sampleCount}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // UI渲染详情
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
                        text = "UI渲染详情",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        BenchmarkDetailItem(
                            label = "最低帧时间",
                            value = "${String.format("%.1f", benchmark.uiRenderPerformance.minFrameTime)}ms"
                        )
                        BenchmarkDetailItem(
                            label = "平均帧时间",
                            value = "${String.format("%.1f", benchmark.uiRenderPerformance.averageFrameTime)}ms"
                        )
                        BenchmarkDetailItem(
                            label = "最高帧时间",
                            value = "${String.format("%.1f", benchmark.uiRenderPerformance.maxFrameTime)}ms"
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(4.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        BenchmarkDetailItem(
                            label = "FPS",
                            value = String.format("%.1f", benchmark.uiRenderPerformance.fps)
                        )
                        BenchmarkDetailItem(
                            label = "卡顿率",
                            value = "${String.format("%.1f", benchmark.uiRenderPerformance.jankPercentage)}%"
                        )
                        BenchmarkDetailItem(
                            label = "样本数",
                            value = benchmark.uiRenderPerformance.sampleCount.toString()
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun BenchmarkMetricItem(label: String, value: String, description: String, color: Color) {
    Card(
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium
                )
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            
            Text(
                text = value,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = color
            )
        }
    }
}

@Composable
fun BenchmarkDetailItem(label: String, value: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium
        )
    }
}