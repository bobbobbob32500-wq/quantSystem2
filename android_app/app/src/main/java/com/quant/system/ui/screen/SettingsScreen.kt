package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.quant.system.data.model.AppUpdatePayload
import com.quant.system.ui.screen.viewmodel.DebugPanelState
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

private data class SettingsOverviewCard(
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
    aiInferenceMode: String,
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
    onSaveAiInferenceMode: (String) -> Unit,
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
    val aiModeInput = remember(aiInferenceMode) { mutableStateOf(aiInferenceMode) }
    val watchlistInput = remember(watchlistSymbols) { mutableStateOf(watchlistSymbols.joinToString(",")) }
    val silentStartInput = remember(silentStart) { mutableStateOf(silentStart) }
    val silentEndInput = remember(silentEnd) { mutableStateOf(silentEnd) }
    val priorityKeywordsInput = remember(signalPriorityKeywords) { mutableStateOf(signalPriorityKeywords) }
    val retentionDaysInput = remember(notificationLogRetentionDays) { mutableStateOf(notificationLogRetentionDays.toString()) }

    val overviewCards = remember(currentVersionName, currentVersionCode, isNotificationPermissionGranted, currentBaseUrl) {
        listOf(
            SettingsOverviewCard("版本", "v$currentVersionName", "构建号 $currentVersionCode"),
            SettingsOverviewCard("通知", if (isNotificationPermissionGranted) "已开启" else "未开启", "关键提醒状态"),
            SettingsOverviewCard("连接", if (currentBaseUrl.isNotBlank()) "已配置" else "未配置", "可在下方测试连接"),
        )
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            TopBar(
                title = "设置",
                subtitle = "连接、通知、策略与个性化配置都收在这里，按主题分段管理。",
                eyebrow = "Control Panel",
            )
        }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onTestConnection) }
        }

        item {
            HeroSection(
                title = "控制台",
                value = if (currentBaseUrl.isNotBlank()) "已接通" else "待配置",
                subtitle = "先确认连接与通知，再调整策略与显示偏好。",
                stats = listOf(
                    Triple("版本", currentVersionName, ""),
                    Triple("通知", if (isNotificationPermissionGranted) "开" else "关", ""),
                    Triple("日志", notificationLogsCount.toString(), ""),
                ),
            )
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                overviewCards.forEach { card ->
                    SettingsOverviewCardItem(card = card, modifier = Modifier.weight(1f))
                }
            }
        }

        item {
            SettingSectionCard(title = "版本与更新") {
                SecondaryButton(
                    text = if (isCheckingUpdate) "检查中..." else "检查更新",
                    onClick = onCheckUpdate,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isCheckingUpdate,
                )
                latestUpdate?.takeIf { !it.apkUrl.isNullOrBlank() }?.let {
                    DetailCard(
                        title = "发现新版本 ${it.latestVersionName ?: ""}".trim(),
                        lines = buildList {
                            add("版本号：${it.latestVersionCode ?: "--"}")
                            it.publishedAt?.takeIf { value -> value.isNotBlank() }?.let { value -> add("发布时间：$value") }
                            it.changelog?.takeIf { value -> value.isNotBlank() }?.let { value -> add("更新内容：$value") }
                        },
                    )
                    PrimaryButton(
                        text = "下载并安装更新",
                        onClick = { onInstallUpdate(it.apkUrl.orEmpty()) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        item {
            SettingSectionCard(title = "通知与提醒") {
                DetailCard("通知权限", listOf(if (isNotificationPermissionGranted) "状态：已开启" else "状态：未开启"))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PrimaryButton(
                        text = if (isNotificationPermissionGranted) "重新检测权限" else "开启通知权限",
                        onClick = onRequestNotificationPermission,
                        modifier = Modifier.weight(1f),
                    )
                    SecondaryButton(
                        text = "发送测试通知",
                        onClick = onSendTestNotification,
                        modifier = Modifier.weight(1f),
                    )
                }
                if (showOpenNotificationSettings) {
                    SecondaryButton(
                        text = "打开系统通知设置",
                        onClick = onOpenNotificationSettings,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                SettingSwitchRow("仅提醒高优先级信号", notifyHighPrioritySignalOnly, onSetHighPrioritySignalOnly)
                SettingSwitchRow("动作完成提醒", notifyActionCompleteEnabled, onSetActionCompleteNotifyEnabled)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = silentStartInput.value,
                        onValueChange = { silentStartInput.value = it },
                        modifier = Modifier.weight(1f),
                        label = { Text("静默开始") },
                        supportingText = { Text("HH:mm") },
                        singleLine = true,
                        shape = RoundedCornerShape(18.dp),
                    )
                    OutlinedTextField(
                        value = silentEndInput.value,
                        onValueChange = { silentEndInput.value = it },
                        modifier = Modifier.weight(1f),
                        label = { Text("静默结束") },
                        supportingText = { Text("HH:mm") },
                        singleLine = true,
                        shape = RoundedCornerShape(18.dp),
                    )
                }
                SecondaryButton(
                    text = "保存静默时段${if (isCrossDayWindow(silentStartInput.value, silentEndInput.value)) "（跨天）" else ""}",
                    onClick = { onSaveSilentWindow(silentStartInput.value, silentEndInput.value) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = priorityKeywordsInput.value,
                    onValueChange = { priorityKeywordsInput.value = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("高优先级关键词") },
                    supportingText = { Text("英文逗号分隔，例如 buy,strong,breakout,突破") },
                    shape = RoundedCornerShape(18.dp),
                )
                SecondaryButton(
                    text = "保存关键词规则",
                    onClick = { onSaveSignalPriorityKeywords(priorityKeywordsInput.value) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = retentionDaysInput.value,
                    onValueChange = { retentionDaysInput.value = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("通知日志保留天数") },
                    supportingText = { Text("范围 1-30 天") },
                    singleLine = true,
                    shape = RoundedCornerShape(18.dp),
                )
                SecondaryButton(
                    text = "保存日志保留天数",
                    onClick = { onSaveNotificationLogRetentionDays(retentionDaysInput.value.toIntOrNull() ?: notificationLogRetentionDays) },
                    modifier = Modifier.fillMaxWidth(),
                )
                SecondaryButton(
                    text = "查看通知触发日志（$notificationLogsCount）",
                    onClick = onOpenNotificationLogs,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        item {
            SettingSectionCard(title = "显示与个性化") {
                SettingSwitchRow("高对比模式", highContrastEnabled, onToggleHighContrast)
                OutlinedTextField(
                    value = strategyInput.value,
                    onValueChange = { strategyInput.value = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("默认策略") },
                    singleLine = true,
                    shape = RoundedCornerShape(18.dp),
                )
                PrimaryButton(
                    text = "保存默认策略",
                    onClick = { onSaveDefaultStrategy(strategyInput.value.trim()) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = moduleOrderInput.value,
                    onValueChange = { moduleOrderInput.value = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("首页模块顺序") },
                    supportingText = { Text("示例：overview,task,health,metrics,signals") },
                    singleLine = true,
                    shape = RoundedCornerShape(18.dp),
                )
                SecondaryButton(
                    text = "保存模块顺序",
                    onClick = { onSaveHomeModuleOrder(moduleOrderInput.value.trim()) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = watchlistInput.value,
                    onValueChange = { watchlistInput.value = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("自选池代码") },
                    supportingText = { Text("英文逗号分隔，例如 000001,600519") },
                    shape = RoundedCornerShape(18.dp),
                )
                PrimaryButton(
                    text = "保存自选池",
                    onClick = {
                        val symbols = watchlistInput.value.split(",").map { it.trim() }.filter { it.isNotBlank() }
                        onSaveWatchlist(symbols)
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        item {
            SettingSectionCard(title = "连接与联调") {
                OutlinedTextField(
                    value = baseUrlInput,
                    onValueChange = onBaseUrlChange,
                    modifier = Modifier
                        .fillMaxWidth()
                        .semantics { this.contentDescription = "API 地址输入框" },
                    label = { Text("API 地址") },
                    supportingText = { Text("示例：http://101.133.149.141/") },
                    singleLine = true,
                    shape = RoundedCornerShape(18.dp),
                )
                DetailCard("当前生效地址", listOf(currentBaseUrl))
                Text(
                    text = "AI 推理策略",
                    style = MaterialTheme.typography.titleSmall,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    InferenceModeButton("自动", aiModeInput.value == "auto", Modifier.weight(1f)) { aiModeInput.value = "auto" }
                    InferenceModeButton("云端优先", aiModeInput.value == "cloud", Modifier.weight(1f)) { aiModeInput.value = "cloud" }
                    InferenceModeButton("本地优先", aiModeInput.value == "local", Modifier.weight(1f)) { aiModeInput.value = "local" }
                }
                SecondaryButton(
                    text = "保存 AI 推理策略",
                    onClick = { onSaveAiInferenceMode(aiModeInput.value) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PrimaryButton(
                        text = if (isSaving) "处理中..." else "测试连接",
                        onClick = onTestConnection,
                        modifier = Modifier.weight(1f),
                        enabled = !isSaving,
                    )
                    SecondaryButton(
                        text = "复制地址",
                        onClick = onCopyBaseUrl,
                        modifier = Modifier.weight(1f),
                    )
                }
                PrimaryButton(
                    text = if (isSaving) "保存中..." else "保存并使用该地址",
                    onClick = onSave,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isSaving,
                )
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
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SecondaryButton(
                        text = "复制 Docs",
                        onClick = onCopyDocsUrl,
                        modifier = Modifier.weight(1f),
                    )
                    PrimaryButton(
                        text = "打开 Docs",
                        onClick = onOpenDocs,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }

        item {
            SettingSectionCard(title = "性能优化") {
                DetailCard(
                    title = "优化功能",
                    lines = listOf(
                        "网络连接优化：实时监控、智能重试、弱网络适配",
                        "数据同步优化：增量更新、智能缓存、后台同步",
                        "性能优化：内存管理、线程池优化、性能监控",
                        "稳定性提升：异常处理、崩溃恢复、错误监控",
                        "用户体验优化：加载状态、交互反馈、骨架屏",
                    ),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SecondaryButton(
                        text = "优化测试",
                        onClick = onOpenOptimizationTest,
                        modifier = Modifier.weight(1f),
                    )
                    PrimaryButton(
                        text = "优化报告",
                        onClick = onOpenOptimizationReport,
                        modifier = Modifier.weight(1f),
                    )
                }
                PrimaryButton(
                    text = "打开优化启动器",
                    onClick = onOpenOptimizationLauncher,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun SettingSectionCard(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
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
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
            )
            content()
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
        shape = RoundedCornerShape(22.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(card.title, style = MaterialTheme.typography.labelMedium, color = TextSecondary)
            Text(card.value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = TextPrimary)
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(title, color = TextPrimary)
            Switch(checked = checked, onCheckedChange = onCheckedChange)
        }
    }
}

@Composable
private fun RowScope.InferenceModeButton(
    label: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    if (selected) {
        PrimaryButton(text = label, onClick = onClick, modifier = modifier)
    } else {
        SecondaryButton(text = label, onClick = onClick, modifier = modifier)
    }
}

private fun isCrossDayWindow(start: String, end: String): Boolean {
    val s = start.split(":").firstOrNull()?.toIntOrNull() ?: return false
    val e = end.split(":").firstOrNull()?.toIntOrNull() ?: return false
    return s > e
}
