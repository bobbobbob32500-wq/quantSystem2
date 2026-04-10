package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.Icon
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.DeveloperMode
import androidx.compose.material.icons.filled.RocketLaunch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import android.content.Intent
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import com.quant.system.data.model.AppUpdatePayload
import com.quant.system.ui.screen.viewmodel.DebugPanelState
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class SettingsOverviewCard(
    val id: String,
    val title: String,
    val value: String,
    val subtitle: String,
)

@Composable
fun SettingsScreen(
    currentBaseUrl: String,
    baseUrlInput: String,
    message: String?,
    noticeType: NoticeType,
    isSaving: Boolean,
    currentVersionName: String,
    currentVersionCode: Int,
    isCheckingUpdate: Boolean,
    latestUpdate: AppUpdatePayload?,
    highContrastEnabled: Boolean,
    defaultStrategy: String,
    homeModuleOrder: String,
    watchlistSymbols: List<String>,
    isNotificationPermissionGranted: Boolean,
    notifyHighPrioritySignalOnly: Boolean,
    notifyActionCompleteEnabled: Boolean,
    silentStart: String,
    silentEnd: String,
    signalPriorityKeywords: String,
    notificationLogRetentionDays: Int,
    notificationLogsCount: Int,
    debugPanel: DebugPanelState,
    onBaseUrlChange: (String) -> Unit,
    onToggleHighContrast: (Boolean) -> Unit,
    onSave: () -> Unit,
    onTestConnection: () -> Unit,
    onCheckUpdate: () -> Unit,
    onInstallUpdate: (String) -> Unit,
    onRequestNotificationPermission: () -> Unit,
    onSendTestNotification: () -> Unit,
    showOpenNotificationSettings: Boolean,
    onOpenNotificationSettings: () -> Unit,
    onSaveDefaultStrategy: (String) -> Unit,
    onSaveHomeModuleOrder: (String) -> Unit,
    onSaveWatchlist: (List<String>) -> Unit,
    onSetHighPrioritySignalOnly: (Boolean) -> Unit,
    onSetActionCompleteNotifyEnabled: (Boolean) -> Unit,
    onSaveSilentWindow: (String, String) -> Unit,
    onSaveSignalPriorityKeywords: (String) -> Unit,
    onSaveNotificationLogRetentionDays: (Int) -> Unit,
    onOpenNotificationLogs: () -> Unit,
    onCopyBaseUrl: () -> Unit,
    onCopyDocsUrl: () -> Unit,
    onOpenDocs: () -> Unit,
    onOpenOptimizationTest: () -> Unit,
    onOpenOptimizationReport: () -> Unit,
    onOpenOptimizationLauncher: () -> Unit,
) {
    val strategyInput = remember(defaultStrategy) { mutableStateOf(defaultStrategy) }
    val moduleOrderInput = remember(homeModuleOrder) { mutableStateOf(homeModuleOrder) }
    val watchlistInput = remember(watchlistSymbols) { mutableStateOf(watchlistSymbols.joinToString(",")) }
    val silentStartInput = remember(silentStart) { mutableStateOf(silentStart) }
    val silentEndInput = remember(silentEnd) { mutableStateOf(silentEnd) }
    val priorityKeywordsInput = remember(signalPriorityKeywords) { mutableStateOf(signalPriorityKeywords) }
    val retentionDaysInput = remember(notificationLogRetentionDays) { mutableStateOf(notificationLogRetentionDays.toString()) }

    val overviewCards = remember(
        currentVersionName,
        currentVersionCode,
        isNotificationPermissionGranted,
        currentBaseUrl,
    ) {
        listOf(
            SettingsOverviewCard(
                id = "version",
                title = "当前版本",
                value = "v$currentVersionName",
                subtitle = "构建号 $currentVersionCode",
            ),
            SettingsOverviewCard(
                id = "notify",
                title = "通知权限",
                value = if (isNotificationPermissionGranted) "已开启" else "未开启",
                subtitle = "关键提醒状态",
            ),
            SettingsOverviewCard(
                id = "api",
                title = "API连接",
                value = if (currentBaseUrl.isNotBlank()) "已配置" else "未配置",
                subtitle = "可在下方测试连接",
            ),
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { ScreenHeader("设置中心", "连接、通知、策略与个性化配置") }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onTestConnection) }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                overviewCards.forEach { card ->
                    SettingsOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                }
            }
        }

        item { SectionHeader("版本与更新") }
        item {
            Button(onClick = onCheckUpdate, modifier = Modifier.fillMaxWidth(), enabled = !isCheckingUpdate) {
                Text(if (isCheckingUpdate) "检查中..." else "检查更新")
            }
        }
        if (latestUpdate != null && !latestUpdate.apkUrl.isNullOrBlank()) {
            item {
                DetailCard(
                    title = "发现新版本 ${latestUpdate.latestVersionName ?: ""}".trim(),
                    lines = buildList {
                        add("版本号：${latestUpdate.latestVersionCode ?: "--"}")
                        latestUpdate.publishedAt?.takeIf { it.isNotBlank() }?.let { add("发布时间：$it") }
                        latestUpdate.changelog?.takeIf { it.isNotBlank() }?.let { add("更新内容：$it") }
                    },
                )
            }
            item {
                Button(
                    onClick = { onInstallUpdate(latestUpdate.apkUrl.orEmpty()) },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("下载并安装更新") }
            }
        }

        item { SectionHeader("通知与提醒") }
        item { DetailCard("通知权限", listOf(if (isNotificationPermissionGranted) "状态：已开启" else "状态：未开启")) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onRequestNotificationPermission, modifier = Modifier.weight(1f)) {
                    Text(if (isNotificationPermissionGranted) "重新检测权限" else "开启通知权限")
                }
                OutlinedButton(onClick = onSendTestNotification, modifier = Modifier.weight(1f)) {
                    Text("发送测试通知")
                }
            }
        }
        if (showOpenNotificationSettings) {
            item {
                OutlinedButton(onClick = onOpenNotificationSettings, modifier = Modifier.fillMaxWidth()) {
                    Text("打开系统通知设置")
                }
            }
        }
        item {
            SettingSwitchRow(
                title = "仅提醒高优先级信号",
                checked = notifyHighPrioritySignalOnly,
                onCheckedChange = onSetHighPrioritySignalOnly,
            )
        }
        item {
            SettingSwitchRow(
                title = "动作完成提醒",
                checked = notifyActionCompleteEnabled,
                onCheckedChange = onSetActionCompleteNotifyEnabled,
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = silentStartInput.value,
                    onValueChange = { silentStartInput.value = it },
                    modifier = Modifier.weight(1f),
                    label = { Text("静默开始") },
                    supportingText = { Text("HH:mm") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = silentEndInput.value,
                    onValueChange = { silentEndInput.value = it },
                    modifier = Modifier.weight(1f),
                    label = { Text("静默结束") },
                    supportingText = { Text("HH:mm") },
                    singleLine = true,
                )
            }
        }
        item {
            OutlinedButton(
                onClick = { onSaveSilentWindow(silentStartInput.value, silentEndInput.value) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("保存静默时段${if (isCrossDayWindow(silentStartInput.value, silentEndInput.value)) "（跨天）" else ""}")
            }
        }
        item {
            OutlinedTextField(
                value = priorityKeywordsInput.value,
                onValueChange = { priorityKeywordsInput.value = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("高优先级关键词") },
                supportingText = { Text("英文逗号分隔，例如 buy,strong,breakout,突破") },
            )
        }
        item {
            OutlinedButton(
                onClick = { onSaveSignalPriorityKeywords(priorityKeywordsInput.value) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("保存关键词规则")
            }
        }
        item {
            OutlinedTextField(
                value = retentionDaysInput.value,
                onValueChange = { retentionDaysInput.value = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("通知日志保留天数") },
                supportingText = { Text("范围 1-30 天") },
                singleLine = true,
            )
        }
        item {
            OutlinedButton(
                onClick = { onSaveNotificationLogRetentionDays(retentionDaysInput.value.toIntOrNull() ?: notificationLogRetentionDays) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("保存日志保留天数")
            }
        }
        item {
            OutlinedButton(onClick = onOpenNotificationLogs, modifier = Modifier.fillMaxWidth()) {
                Text("查看通知触发日志（$notificationLogsCount）")
            }
        }

        item { SectionHeader("显示与个性化") }
        item {
            SettingSwitchRow(
                title = "高对比模式",
                checked = highContrastEnabled,
                onCheckedChange = onToggleHighContrast,
            )
        }
        item {
            OutlinedTextField(
                value = strategyInput.value,
                onValueChange = { strategyInput.value = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("默认策略") },
                singleLine = true,
            )
        }
        item { Button(onClick = { onSaveDefaultStrategy(strategyInput.value.trim()) }, modifier = Modifier.fillMaxWidth()) { Text("保存默认策略") } }
        item {
            OutlinedTextField(
                value = moduleOrderInput.value,
                onValueChange = { moduleOrderInput.value = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("首页模块顺序") },
                supportingText = { Text("示例：overview,task,health,metrics,signals") },
                singleLine = true,
            )
        }
        item { Button(onClick = { onSaveHomeModuleOrder(moduleOrderInput.value.trim()) }, modifier = Modifier.fillMaxWidth()) { Text("保存模块顺序") } }
        item {
            OutlinedTextField(
                value = watchlistInput.value,
                onValueChange = { watchlistInput.value = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("自选池代码") },
                supportingText = { Text("英文逗号分隔，例如 000001,600519") },
            )
        }
        item {
            Button(
                onClick = {
                    val symbols = watchlistInput.value.split(",").map { it.trim() }.filter { it.isNotBlank() }
                    onSaveWatchlist(symbols)
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("保存自选池") }
        }

        item { SectionHeader("连接与联调") }
        item {
            OutlinedTextField(
                value = baseUrlInput,
                onValueChange = onBaseUrlChange,
                modifier = Modifier.fillMaxWidth().semantics { contentDescription = "API 地址输入框" },
                label = { Text("API 地址") },
                supportingText = { Text("示例：https://silvicultural-nonrectangularly-lyle.ngrok-free.dev/") },
                singleLine = true,
            )
        }
        item { DetailCard("当前生效地址", listOf(currentBaseUrl)) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onTestConnection, modifier = Modifier.weight(1f), enabled = !isSaving) {
                    Text(if (isSaving) "处理中..." else "测试连接")
                }
                OutlinedButton(onClick = onCopyBaseUrl, modifier = Modifier.weight(1f)) { Text("复制地址") }
            }
        }
        item {
            Button(onClick = onSave, modifier = Modifier.fillMaxWidth(), enabled = !isSaving) {
                Text(if (isSaving) "保存中..." else "保存并使用该地址")
            }
        }
        item {
            DetailCard(
                title = "开发联调",
                lines = listOf(
                    "后端状态：${debugPanel.backendStatusLabel}",
                    "服务标识：${debugPanel.backendServiceName}",
                    "接口文档：${debugPanel.backendDocsUrl}",
                    "最近检测：${debugPanel.lastCheckedAtLabel ?: "--"}",
                    "协作机制：${debugPanel.contractStatusLabel}",
                ),
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onCopyDocsUrl, modifier = Modifier.weight(1f)) { Text("复制 Docs") }
                Button(onClick = onOpenDocs, modifier = Modifier.weight(1f)) { Text("打开 Docs") }
            }
        }

        item { SectionHeader("性能优化") }
        item {
            DetailCard(
                title = "优化功能",
                lines = listOf(
                    "网络连接优化：实时监控、智能重试、弱网络适配",
                    "数据同步优化：增量更新、智能缓存、后台同步",
                    "性能优化：内存管理、线程池优化、性能监控",
                    "稳定性提升：异常处理、崩溃恢复、错误监控",
                    "用户体验优化：加载状态、交互反馈、骨架屏"
                ),
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = onOpenOptimizationTest,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(
                        imageVector = Icons.Default.BugReport,
                        contentDescription = "优化测试",
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("优化测试")
                }
                Button(
                    onClick = onOpenOptimizationReport,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(
                        imageVector = Icons.Default.Assessment,
                        contentDescription = "优化报告",
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("优化报告")
                }
            }
        }
        item {
            Button(
                onClick = onOpenOptimizationLauncher,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(
                    imageVector = Icons.Default.RocketLaunch,
                    contentDescription = "优化启动器",
                    modifier = Modifier.size(20.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("打开优化启动器")
            }
        }
    }
}

@Composable
private fun SettingsOverviewCardItem(
    card: SettingsOverviewCard,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = Surface),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(card.title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(card.value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = TextPrimary)
            Text(card.subtitle, style = MaterialTheme.typography.bodySmall, color = TextSecondary)
        }
    }
}

@Composable
private fun SettingSwitchRow(
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(title, modifier = Modifier.padding(top = 12.dp))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

private fun isCrossDayWindow(start: String, end: String): Boolean {
    val s = start.split(":").firstOrNull()?.toIntOrNull() ?: return false
    val e = end.split(":").firstOrNull()?.toIntOrNull() ?: return false
    return s > e
}
