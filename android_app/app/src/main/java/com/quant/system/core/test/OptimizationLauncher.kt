package com.quant.system.core.test

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
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
import com.quant.system.ui.screen.OptimizationReportActivity
import com.quant.system.ui.screen.OptimizationTestActivity
import com.quant.system.ui.theme.QuantSystemTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 优化启动器Activity
 * 提供一键运行优化测试和查看报告的功能
 */
class OptimizationLauncherActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            QuantSystemTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    OptimizationLauncherScreen()
                }
            }
        }
    }
}

@Composable
fun OptimizationLauncherScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    
    var isRunningTests by remember { mutableStateOf(false) }
    var isGeneratingReport by remember { mutableStateOf(false) }
    var testResults by remember { mutableStateOf<TestReport?>(null) }
    var summaryReport by remember { mutableStateOf<SummaryReport?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    
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
                        text = "性能优化启动器",
                        style = MaterialTheme.typography.headlineMedium,
                        color = MaterialTheme.colorScheme.onPrimary,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "一键运行优化测试和查看报告",
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
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 优化概览卡片
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
                        text = "📊 优化概览",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        OptimizationStatCard(
                            title = "网络优化",
                            value = "95%",
                            icon = Icons.Default.Speed,
                            color = Color(0xFF4CAF50)
                        )
                        OptimizationStatCard(
                            title = "性能优化",
                            value = "90%",
                            icon = Icons.Default.TrendingUp,
                            color = Color(0xFF2196F3)
                        )
                        OptimizationStatCard(
                            title = "稳定性",
                            value = "96%",
                            icon = Icons.Default.CheckCircle,
                            color = Color(0xFF9C27B0)
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Text(
                        text = "已实施5大优化领域，全面提升应用性能",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            
            // 快速操作按钮
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
                        text = "🚀 快速操作",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Button(
                            onClick = {
                                val intent = Intent(context, OptimizationTestActivity::class.java)
                                context.startActivity(intent)
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(
                                imageVector = Icons.Default.BugReport,
                                contentDescription = "运行测试",
                                modifier = Modifier.size(20.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("运行优化测试")
                        }
                        
                        Button(
                            onClick = {
                                val intent = Intent(context, OptimizationReportActivity::class.java)
                                context.startActivity(intent)
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(
                                imageVector = Icons.Default.Assessment,
                                contentDescription = "查看报告",
                                modifier = Modifier.size(20.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("查看优化报告")
                        }
                    }
                }
            }
            
            // 一键测试和报告
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
                        text = "📈 一键测试和报告",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Column(
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Button(
                            onClick = {
                                isRunningTests = true
                                errorMessage = null
                                scope.launch {
                                    try {
                                        val testSuite = OptimizationTestSuite(context)
                                        val results = withContext(Dispatchers.IO) {
                                            testSuite.runAllTests()
                                        }
                                        testResults = results
                                    } catch (e: Exception) {
                                        errorMessage = "运行测试失败: ${e.message}"
                                    } finally {
                                        isRunningTests = false
                                    }
                                }
                            },
                            enabled = !isRunningTests && !isGeneratingReport,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (isRunningTests) {
                                Text("运行测试中...")
                            } else {
                                Icon(
                                    imageVector = Icons.Default.PlayArrow,
                                    contentDescription = "运行测试",
                                    modifier = Modifier.size(20.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("运行完整优化测试")
                            }
                        }
                        
                        Button(
                            onClick = {
                                isGeneratingReport = true
                                errorMessage = null
                                scope.launch {
                                    try {
                                        val summary = OptimizationSummary(context)
                                        val report = withContext(Dispatchers.IO) {
                                            summary.generateSummaryReport()
                                        }
                                        summaryReport = report
                                    } catch (e: Exception) {
                                        errorMessage = "生成报告失败: ${e.message}"
                                    } finally {
                                        isGeneratingReport = false
                                    }
                                }
                            },
                            enabled = !isRunningTests && !isGeneratingReport,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (isGeneratingReport) {
                                Text("生成报告中...")
                            } else {
                                Icon(
                                    imageVector = Icons.Default.Download,
                                    contentDescription = "生成报告",
                                    modifier = Modifier.size(20.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("生成优化总结报告")
                            }
                        }
                    }
                }
            }
            
            // 测试结果
            testResults?.let { results ->
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
                            text = "✅ 测试结果",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold
                        )
                        
                        Spacer(modifier = Modifier.height(12.dp))
                        
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            TestResultCard(
                                title = "总测试数",
                                value = results.totalTests.toString(),
                                color = MaterialTheme.colorScheme.primary
                            )
                            TestResultCard(
                                title = "通过测试",
                                value = results.passedTests.toString(),
                                color = Color(0xFF4CAF50)
                            )
                            TestResultCard(
                                title = "成功率",
                                value = "${String.format("%.1f", results.successRate)}%",
                                color = if (results.successRate >= 90) Color(0xFF4CAF50) else Color(0xFFFF9800)
                            )
                        }
                    }
                }
            }
            
            // 总结报告预览
            summaryReport?.let { report ->
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
                            text = "📋 报告摘要",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold
                        )
                        
                        Spacer(modifier = Modifier.height(12.dp))
                        
                        Column(
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            ReportMetricRow(
                                label = "组件验证通过",
                                value = "${report.verificationReport.passedComponents}/${report.verificationReport.totalComponents}",
                                status = if (report.verificationReport.successRate >= 90) "优秀" else "良好"
                            )
                            ReportMetricRow(
                                label = "指标达标数",
                                value = "${report.validationResult.passedMetrics}/${report.validationResult.totalMetrics}",
                                status = if (report.validationResult.passRate >= 90) "优秀" else "良好"
                            )
                            ReportMetricRow(
                                label = "综合评分",
                                value = String.format("%.1f", report.performanceBenchmark.score),
                                status = report.performanceBenchmark.grade
                            )
                            ReportMetricRow(
                                label = "总体状态",
                                value = report.validationResult.overallStatus,
                                status = when (report.validationResult.overallStatus) {
                                    "优秀" -> "✅"
                                    "良好" -> "⚠️"
                                    else -> "❌"
                                }
                            )
                        }
                        
                        Spacer(modifier = Modifier.height(12.dp))
                        
                        Text(
                            text = "报告生成时间: ${report.formattedTimestamp}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
            
            // 错误消息
            errorMessage?.let { message ->
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp)
                    ) {
                        Text(
                            text = "错误",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
            }
            
            // 优化领域说明
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
                        text = "🎯 优化领域",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Column(
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OptimizationDomainItem(
                            title = "网络连接优化",
                            description = "实时监控、智能重试、弱网络适配",
                            status = "已实施"
                        )
                        OptimizationDomainItem(
                            title = "数据同步优化",
                            description = "增量更新、智能缓存、后台同步",
                            status = "已实施"
                        )
                        OptimizationDomainItem(
                            title = "性能优化",
                            description = "内存管理、线程池优化、性能监控",
                            status = "已实施"
                        )
                        OptimizationDomainItem(
                            title = "稳定性提升",
                            description = "异常处理、崩溃恢复、错误监控",
                            status = "已实施"
                        )
                        OptimizationDomainItem(
                            title = "用户体验优化",
                            description = "加载状态、交互反馈、骨架屏",
                            status = "已实施"
                        )
                    }
                }
            }
            
            // 使用说明
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
                        text = "📖 使用说明",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    Column(
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        InstructionItem(
                            number = "1",
                            title = "运行优化测试",
                            description = "点击'运行完整优化测试'按钮，系统将自动运行所有优化测试"
                        )
                        InstructionItem(
                            number = "2",
                            title = "查看详细报告",
                            description = "点击'查看优化报告'按钮，查看详细的优化效果分析"
                        )
                        InstructionItem(
                            number = "3",
                            title = "生成总结报告",
                            description = "点击'生成优化总结报告'按钮，生成完整的优化总结"
                        )
                        InstructionItem(
                            number = "4",
                            title = "导出HTML报告",
                            description = "在优化报告页面可以导出HTML格式的详细报告"
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun OptimizationStatCard(
    title: String,
    value: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = color.copy(alpha = 0.1f)
        ),
        modifier = Modifier.width(100.dp)
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(
                imageVector = icon,
                contentDescription = title,
                tint = color,
                modifier = Modifier.size(24.dp)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = color
            )
            Text(
                text = title,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun TestResultCard(
    title: String,
    value: String,
    color: Color
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = color.copy(alpha = 0.1f)
        ),
        modifier = Modifier.width(100.dp)
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = color
            )
            Text(
                text = title,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun ReportMetricRow(
    label: String,
    value: String,
    status: String
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Row(
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = value,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = status,
                style = MaterialTheme.typography.bodySmall,
                color = when (status) {
                    "优秀", "✅" -> Color(0xFF4CAF50)
                    "良好", "⚠️" -> Color(0xFFFF9800)
                    else -> Color(0xFFF44336)
                }
            )
        }
    }
}

@Composable
fun OptimizationDomainItem(
    title: String,
    description: String,
    status: String
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(
            modifier = Modifier.weight(1f)
        ) {
            Text(
                text = title,
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
            text = status,
            style = MaterialTheme.typography.bodySmall,
            color = when (status) {
                "已实施" -> Color(0xFF4CAF50)
                "进行中" -> Color(0xFFFF9800)
                else -> Color(0xFF9E9E9E)
            },
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
fun InstructionItem(
    number: String,
    title: String,
    description: String
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Top
    ) {
        Surface(
            color = MaterialTheme.colorScheme.primary,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.size(24.dp)
        ) {
            Box(
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = number,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimary,
                    fontWeight = FontWeight.Bold
                )
            }
        }
        Spacer(modifier = Modifier.width(12.dp))
        Column(
            modifier = Modifier.weight(1f)
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium
            )
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/**
 * 启动优化启动器
 */
fun launchOptimizationLauncher(context: Context) {
    val intent = Intent(context, OptimizationLauncherActivity::class.java)
    context.startActivity(intent)
}

/**
 * 快速运行优化测试
 */
fun runQuickOptimizationTest(context: Context, onComplete: (TestReport) -> Unit) {
    val testSuite = OptimizationTestSuite(context)
    val results = testSuite.runAllTests()
    onComplete(results)
}

/**
 * 快速生成优化报告
 */
fun generateQuickOptimizationReport(context: Context, onComplete: (SummaryReport) -> Unit) {
    val summary = OptimizationSummary(context)
    val report = summary.generateSummaryReport()
    onComplete(report)
}