package com.quant.system.ui.screen

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.PlaylistAddCheck
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.QueryStats
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.quant.system.ui.screen.viewmodel.DashboardViewModel
import com.quant.system.ui.screen.viewmodel.DashboardViewModelFactory
import com.quant.system.ui.screen.viewmodel.NavigationTarget
import com.quant.system.ui.theme.Background
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.QuantSystemTheme
import com.quant.system.ui.theme.Surface as AppSurface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary
import kotlinx.coroutines.launch

private enum class ScreenDestination(val title: String) {
    Actions("动作中心"),
    History("执行历史"),
    Settings("设置"),
    Strategy("策略中心"),
    Analytics("复盘统计"),
    NotificationLogs("通知日志"),
    AIAssistant("AI管家"),
    AlertCenter("预警中心"),
    RealtimeWatcher("盯盘助手"),
    DeepReview("深度复盘"),
    KnowledgeBase("知识库"),
}

private data class DrawerDestination(
    val label: String,
    val subtitle: String,
    val selected: Boolean,
    val onClick: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen() {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    val application = context.applicationContext as android.app.Application
    val viewModel: DashboardViewModel = viewModel(factory = DashboardViewModelFactory(application))
    val state = viewModel.uiState
    val snackbarHostState = remember { SnackbarHostState() }
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    var selectedTab by remember { mutableIntStateOf(0) }
    var extraScreen by remember { mutableStateOf<ScreenDestination?>(null) }
    var wasOverviewVisible by rememberSaveable { mutableStateOf(false) }
    var hasRequestedNotificationPermission by rememberSaveable { mutableStateOf(false) }
    var isNotificationPermissionPermanentlyDenied by rememberSaveable { mutableStateOf(false) }
    val activity = context as? Activity

    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        val permanentlyDenied = !granted &&
            hasRequestedNotificationPermission &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            activity != null &&
            !ActivityCompat.shouldShowRequestPermissionRationale(activity, Manifest.permission.POST_NOTIFICATIONS)
        isNotificationPermissionPermanentlyDenied = permanentlyDenied
        viewModel.onNotificationPermissionResult(granted)
    }

    val tabItems = remember {
        listOf(
            "总览" to Icons.Filled.Assessment,
            "候选池" to Icons.AutoMirrored.Filled.PlaylistAddCheck,
            "信号" to Icons.Filled.QueryStats,
            "持仓" to Icons.AutoMirrored.Filled.ShowChart,
        )
    }

    LaunchedEffect(state.noticeVersion) {
        state.message?.let { snackbarHostState.showSnackbar(it) }
    }

    LaunchedEffect(extraScreen) {
        if (extraScreen == ScreenDestination.AIAssistant) {
            viewModel.refreshAIAssistantState()
        }
    }

    LaunchedEffect(extraScreen, selectedTab) {
        val shouldAutoRefreshOverview = extraScreen == null && selectedTab == 0
        viewModel.setAutoRefreshEnabled(shouldAutoRefreshOverview)
        val shouldWarmRefreshOverview = state.snapshot == null ||
            state.isUsingCachedData ||
            state.networkStatusLabel == "网络状态：未检测"
        if (shouldAutoRefreshOverview && !wasOverviewVisible && shouldWarmRefreshOverview) {
            viewModel.refreshDashboard()
        }
        wasOverviewVisible = shouldAutoRefreshOverview
        if (extraScreen == ScreenDestination.Settings) {
            viewModel.refreshNotificationPermissionStatus()
        }
        when (extraScreen) {
            ScreenDestination.History -> {
                if (state.actionHistory.isEmpty()) {
                    viewModel.refreshActionHistory(showNotice = false)
                }
                if (state.backgroundTasks.isEmpty()) {
                    viewModel.refreshBackgroundTasks(showNotice = false)
                }
                viewModel.startHistoryLivePolling()
            }
            ScreenDestination.Strategy -> {
                if (state.strategies.isEmpty()) {
                    viewModel.refreshStrategies(showNotice = false)
                }
                viewModel.stopHistoryLivePolling()
            }
            ScreenDestination.Analytics -> {
                if (state.analyticsSummary == null) {
                    viewModel.refreshAnalyticsSummary(showNotice = false)
                }
                viewModel.stopHistoryLivePolling()
            }
            ScreenDestination.AlertCenter -> {
                if (state.activeAlerts.isEmpty() || state.alertSummary == null) {
                    viewModel.refreshAlerts(showNotice = false)
                }
                viewModel.stopHistoryLivePolling()
            }
            ScreenDestination.RealtimeWatcher -> {
                if (state.watcherAlerts.isEmpty() || state.watcherSummary == null) {
                    viewModel.refreshWatcherAlerts(showNotice = false)
                }
                viewModel.stopHistoryLivePolling()
            }
            ScreenDestination.KnowledgeBase -> {
                if (state.knowledgeTopics.isEmpty() || state.knowledgeCategories.isEmpty()) {
                    viewModel.refreshKnowledgeTopics(showNotice = false)
                }
                viewModel.stopHistoryLivePolling()
            }
            ScreenDestination.Settings -> {
                viewModel.stopHistoryLivePolling()
            }
            else -> {
                viewModel.stopHistoryLivePolling()
            }
        }
    }

    LaunchedEffect(state.navigationVersion) {
        when (state.pendingNavigationTarget) {
            NavigationTarget.Candidates -> {
                extraScreen = null
                selectedTab = 1
            }
            NavigationTarget.History -> {
                extraScreen = ScreenDestination.History
            }
            null -> Unit
        }
        viewModel.consumeNavigationEvent()
    }

    val title = extraScreen?.title ?: when (selectedTab) {
        1 -> "候选池"
        2 -> "信号"
        3 -> "持仓"
        else -> "总览"
    }
    val subtitle = extraScreen?.let { "低频功能收进抽屉，高频判断留在主导航。" } ?: when (selectedTab) {
        1 -> "按策略切片管理候选、执行选股和推送。"
        2 -> "盘中买卖点与风险提示按时间展开。"
        3 -> "只读账本，按策略分组查看持仓。"
        else -> "系统是否正常、候选是否清晰、卖点是否该先处理。"
    }
    val drawerDestinations = remember(selectedTab, extraScreen) {
        listOf(
            DrawerDestination("总览", "市场状态与今日优先事项", extraScreen == null && selectedTab == 0) {
                extraScreen = null
                selectedTab = 0
            },
            DrawerDestination("候选池", "按策略筛选候选标的", extraScreen == null && selectedTab == 1) {
                extraScreen = null
                selectedTab = 1
            },
            DrawerDestination("信号", "盘中买卖点与预警流", extraScreen == null && selectedTab == 2) {
                extraScreen = null
                selectedTab = 2
            },
            DrawerDestination("持仓", "按策略分类的只读账本", extraScreen == null && selectedTab == 3) {
                extraScreen = null
                selectedTab = 3
            },
            DrawerDestination("动作中心", "执行选股、复盘与监控管理", extraScreen == ScreenDestination.Actions) {
                extraScreen = ScreenDestination.Actions
            },
            DrawerDestination("AI管家", "针对候选与持仓的诊断入口", extraScreen == ScreenDestination.AIAssistant) {
                extraScreen = ScreenDestination.AIAssistant
            },
            DrawerDestination("预警中心", "高优先级提醒与处理建议", extraScreen == ScreenDestination.AlertCenter) {
                extraScreen = ScreenDestination.AlertCenter
            },
            DrawerDestination("执行历史", "动作记录与后台任务", extraScreen == ScreenDestination.History) {
                extraScreen = ScreenDestination.History
            },
            DrawerDestination("策略中心", "四策略结构、胜率与参数", extraScreen == ScreenDestination.Strategy) {
                extraScreen = ScreenDestination.Strategy
            },
            DrawerDestination("复盘统计", "结果汇总与复盘视角", extraScreen == ScreenDestination.Analytics) {
                extraScreen = ScreenDestination.Analytics
            },
            DrawerDestination("知识库", "策略说明与操作知识", extraScreen == ScreenDestination.KnowledgeBase) {
                extraScreen = ScreenDestination.KnowledgeBase
            },
            DrawerDestination("设置", "服务器、通知、AI与日志", extraScreen == ScreenDestination.Settings) {
                extraScreen = ScreenDestination.Settings
            },
        )
    }

    QuantSystemTheme(highContrast = state.highContrastEnabled) {
        ModalNavigationDrawer(
            drawerState = drawerState,
            drawerContent = {
                ModalDrawerSheet(
                    drawerContainerColor = AppSurface,
                    drawerContentColor = TextPrimary,
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 20.dp),
                    ) {
                        Text("QuantFlow", style = androidx.compose.material3.MaterialTheme.typography.labelMedium, color = TextSecondary)
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("量化移动端", style = androidx.compose.material3.MaterialTheme.typography.headlineSmall, color = TextPrimary, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(6.dp))
                        Text("低频页都收进这里，高频判断仍然留在底部主导航。", style = androidx.compose.material3.MaterialTheme.typography.bodySmall, color = TextSecondary)
                    }
                    HorizontalDivider(color = Border)
                    drawerDestinations.forEach { destination ->
                        NavigationDrawerItem(
                            label = {
                                Column {
                                    Text(destination.label)
                                    Text(destination.subtitle, style = androidx.compose.material3.MaterialTheme.typography.bodySmall, color = TextSecondary)
                                }
                            },
                            selected = destination.selected,
                            onClick = {
                                destination.onClick()
                                scope.launch { drawerState.close() }
                            },
                            modifier = Modifier.padding(NavigationDrawerItemDefaults.ItemPadding),
                            colors = NavigationDrawerItemDefaults.colors(
                                selectedContainerColor = SurfaceVariant,
                            ),
                        )
                    }
                }
            },
        ) {
            Scaffold(
                snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
                topBar = {
                    TopAppBar(
                        title = {
                            Column {
                                Text(title, fontWeight = FontWeight.SemiBold)
                                if (extraScreen == null) {
                                    Text(
                                        text = subtitle,
                                        style = androidx.compose.material3.MaterialTheme.typography.bodySmall,
                                        color = TextSecondary,
                                    )
                                }
                            }
                        },
                        navigationIcon = {
                            if (extraScreen != null) {
                                IconButton(onClick = { extraScreen = null }) {
                                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                                }
                            } else {
                                IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                    Icon(Icons.Filled.Menu, contentDescription = "打开导航抽屉")
                                }
                            }
                        },
                        actions = {
                            if (extraScreen == null) {
                                IconButton(onClick = { extraScreen = ScreenDestination.AlertCenter }) {
                                    Icon(Icons.Filled.Warning, contentDescription = "预警中心")
                                }
                                IconButton(onClick = { extraScreen = ScreenDestination.Settings }) {
                                    Icon(Icons.Filled.Settings, contentDescription = "设置")
                                }
                            }
                        },
                        colors = TopAppBarDefaults.topAppBarColors(
                            containerColor = Background,
                            navigationIconContentColor = TextPrimary,
                            titleContentColor = TextPrimary,
                            actionIconContentColor = TextPrimary,
                        ),
                    )
                },
                bottomBar = {
                    if (extraScreen == null) {
                        NavigationBar(containerColor = AppSurface) {
                            tabItems.forEachIndexed { index, item ->
                                NavigationBarItem(
                                    selected = selectedTab == index,
                                    onClick = { selectedTab = index },
                                    icon = { Icon(item.second, contentDescription = item.first) },
                                    label = { Text(item.first) },
                                )
                            }
                        }
                    }
                },
            ) { paddingValues ->
                Surface(modifier = Modifier.padding(paddingValues), color = Background) {
                when (extraScreen) {
                    ScreenDestination.Actions -> ActionsScreen(
                        isActionRunning = state.isActionRunning,
                        runningAction = state.runningAction,
                        actionElapsedSeconds = state.actionElapsedSeconds,
                        actionProgress = state.actionProgress,
                        onGeneratePlan = { viewModel.executeAction("generate_plan") },
                        onRunStockSelection = { viewModel.executeStockSelectionEnhanced(state.defaultStrategy) },
                        onStartRuntime = { viewModel.executeAction("start_monitor_runtime") },
                        onStopRuntime = { viewModel.executeAction("stop_monitor_runtime") },
                        onGenerateReview = { viewModel.executeAction("generate_post_market_review") },
                        onRefresh = viewModel::refreshDashboard,
                    )

                    ScreenDestination.History -> HistoryScreen(
                        records = state.actionHistory,
                        backgroundTasks = state.backgroundTasks,
                        isRefreshing = state.isHistoryLoading,
                        message = state.message,
                        noticeType = state.noticeType,
                        onRefresh = {
                            viewModel.refreshActionHistory(showNotice = true)
                            viewModel.refreshBackgroundTasks(showNotice = false)
                        },
                        onRetryTask = viewModel::retryBackgroundTask,
                    )

                    ScreenDestination.Settings -> SettingsScreen(
                        currentBaseUrl = state.currentBaseUrl,
                        baseUrlInput = state.baseUrlInput,
                        message = state.message,
                        noticeType = state.noticeType,
                        isSaving = state.isSavingSettings,
                        currentVersionName = state.currentVersionName,
                        currentVersionCode = state.currentVersionCode,
                        isCheckingUpdate = state.isCheckingUpdate,
                        latestUpdate = state.latestUpdate,
                        highContrastEnabled = state.highContrastEnabled,
                        defaultStrategy = state.defaultStrategy,
                        homeModuleOrder = state.homeModuleOrder,
                        aiInferenceMode = state.aiInferenceMode,
                        watchlistSymbols = state.watchlist.symbols,
                        isNotificationPermissionGranted = state.isNotificationPermissionGranted,
                        notifyHighPrioritySignalOnly = state.notifyHighPrioritySignalOnly,
                        notifyActionCompleteEnabled = state.notifyActionCompleteEnabled,
                        silentStart = state.silentStart,
                        silentEnd = state.silentEnd,
                        signalPriorityKeywords = state.signalPriorityKeywords,
                        notificationLogRetentionDays = state.notificationLogRetentionDays,
                        notificationLogsCount = state.notificationLogs.size,
                        debugPanel = state.debugPanel,
                        onBaseUrlChange = viewModel::updateBaseUrlInput,
                        onToggleHighContrast = viewModel::setHighContrastEnabled,
                        onSave = viewModel::saveBaseUrl,
                        onTestConnection = viewModel::testConnection,
                        onCheckUpdate = { viewModel.checkForAppUpdate(showNoUpdateNotice = true) },
                        onInstallUpdate = install@{ url ->
                            if (url.isBlank()) return@install
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            runCatching { context.startActivity(intent) }
                                .onSuccess { viewModel.clearUpdateInfo() }
                                .onFailure { scope.launch { snackbarHostState.showSnackbar("无法打开更新链接") } }
                        },
                        onRequestNotificationPermission = {
                            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                                viewModel.onNotificationPermissionResult(true)
                            } else {
                                hasRequestedNotificationPermission = true
                                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                            }
                        },
                        onSendTestNotification = viewModel::sendTestNotification,
                        showOpenNotificationSettings = isNotificationPermissionPermanentlyDenied &&
                            !state.isNotificationPermissionGranted,
                        onOpenNotificationSettings = {
                            val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                                putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            val fallback = Intent(
                                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                Uri.parse("package:${context.packageName}"),
                            ).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                            runCatching { context.startActivity(intent) }
                                .onFailure { context.startActivity(fallback) }
                        },
                        onSaveDefaultStrategy = viewModel::setDefaultStrategy,
                        onSaveHomeModuleOrder = viewModel::setHomeModuleOrder,
                        onSaveAiInferenceMode = viewModel::setAiInferenceMode,
                        onSaveWatchlist = viewModel::updateWatchlist,
                        onSetHighPrioritySignalOnly = viewModel::setHighPrioritySignalOnly,
                        onSetActionCompleteNotifyEnabled = viewModel::setActionCompleteNotifyEnabled,
                        onSaveSilentWindow = viewModel::setSilentWindow,
                        onSaveSignalPriorityKeywords = viewModel::setSignalPriorityKeywords,
                        onSaveNotificationLogRetentionDays = viewModel::setNotificationLogRetentionDays,
                        onOpenNotificationLogs = { extraScreen = ScreenDestination.NotificationLogs },
                        onCopyBaseUrl = {
                            clipboard.setText(AnnotatedString(state.currentBaseUrl))
                            scope.launch { snackbarHostState.showSnackbar("API 地址已复制") }
                        },
                        onCopyDocsUrl = {
                            clipboard.setText(AnnotatedString(state.debugPanel.backendDocsUrl))
                            scope.launch { snackbarHostState.showSnackbar("Docs 地址已复制") }
                        },
                        onOpenDocs = {
                            val docsUrl = state.debugPanel.backendDocsUrl
                            if (docsUrl.isBlank()) return@SettingsScreen
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(docsUrl))
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            runCatching { context.startActivity(intent) }
                                .onFailure { scope.launch { snackbarHostState.showSnackbar("无法打开文档链接") } }
                        },
                        onOpenOptimizationTest = {
                            scope.launch { snackbarHostState.showSnackbar("优化测试页已暂时下线") }
                        },
                        onOpenOptimizationReport = {
                            scope.launch { snackbarHostState.showSnackbar("优化报告页已暂时下线") }
                        },
                        onOpenOptimizationLauncher = {
                            scope.launch { snackbarHostState.showSnackbar("优化启动器已暂时下线") }
                        },
                    )

                    ScreenDestination.Strategy -> StrategyCenterScreen(
                        strategies = state.strategies,
                        message = state.message,
                        noticeType = state.noticeType,
                        onRefresh = { viewModel.refreshStrategies(showNotice = true) },
                        onRunStrategy = viewModel::runStrategy,
                    )

                    ScreenDestination.Analytics -> AnalyticsScreen(
                        summary = state.analyticsSummary,
                        message = state.message,
                        noticeType = state.noticeType,
                        onRefresh = { viewModel.refreshAnalyticsSummary(showNotice = true) },
                    )

                    ScreenDestination.NotificationLogs -> NotificationLogsScreen(
                        logs = state.notificationLogs,
                        message = state.message,
                        noticeType = state.noticeType,
                        onClear = viewModel::clearNotificationLogs,
                        onExport = { text ->
                            clipboard.setText(AnnotatedString(text))
                            scope.launch { snackbarHostState.showSnackbar("日志已复制到剪贴板") }
                        },
                        onRefreshHint = viewModel::sendTestNotification,
                    )

                    ScreenDestination.AIAssistant -> AIAssistantScreen(
                        aiAvailable = state.aiAvailable,
                        aiStatus = state.aiStatus,
                        butlerStatus = state.butlerStatus,
                        onSendMessage = viewModel::sendAIMessage,
                        onQuickAsk = viewModel::aiQuickAsk,
                        onStartButler = viewModel::startButler,
                        onStopButler = viewModel::stopButler,
                        messages = state.aiMessages,
                        inputText = state.aiInputText,
                        inferenceMode = state.aiInferenceMode,
                        onInputTextChange = viewModel::updateAIInputText,
                        onClearHistory = viewModel::clearAIHistory,
                    )

                    ScreenDestination.AlertCenter -> AlertCenterScreen(
                        alerts = state.activeAlerts,
                        summary = state.alertSummary,
                        onAckAlert = viewModel::ackAlert,
                        onRefresh = { viewModel.refreshAlerts(true) },
                    )

                    ScreenDestination.RealtimeWatcher -> RealtimeWatcherScreen(
                        alerts = state.watcherAlerts,
                        summary = state.watcherSummary,
                        onRemoveAlert = viewModel::removeWatcherAlert,
                        onRefresh = { viewModel.refreshWatcherAlerts(true) },
                    )

                    ScreenDestination.DeepReview -> DeepReviewScreen(
                        result = state.deepReviewResult,
                        onRefresh = { viewModel.executeDeepReview() },
                    )

                    ScreenDestination.KnowledgeBase -> KnowledgeBaseScreen(
                        topics = state.knowledgeTopics,
                        categories = state.knowledgeCategories,
                        selectedArticle = state.selectedKnowledgeArticle,
                        onQueryTopic = viewModel::queryKnowledge,
                        onRefresh = { viewModel.refreshKnowledgeTopics(true) },
                    )

                    null -> when (selectedTab) {
                        1 -> StocksScreen(
                            snapshot = state.snapshot,
                            selectionHistory = state.stockSelectionHistory,
                            preferredStrategyKey = state.activeSelectionStrategyKey ?: state.defaultStrategy,
                            selectedHistoryId = state.activeSelectionHistoryId,
                            historyFilterStrategy = state.selectionHistoryFilterStrategy,
                            monitorExpectedActive = state.monitorExpectedActive,
                            isActionRunning = state.isActionRunning,
                            runningAction = state.runningAction,
                            selectionStatusLabel = state.selectionStatusLabel,
                            isRefreshing = state.isLoading,
                            message = state.message,
                            noticeType = state.noticeType,
                            onRefresh = viewModel::refreshDashboard,
                            onRunStockSelection = viewModel::executeStockSelectionEnhanced,
                            onPushSelection = { viewModel.executeAction("push_selection_wecom") },
                            onApplySelectionHistory = viewModel::applyStockSelectionHistory,
                            onChangeHistoryFilterStrategy = viewModel::setSelectionHistoryFilterStrategy,
                            onDeleteSelectionHistory = viewModel::deleteStockSelectionHistory,
                            onClearSelectionHistory = viewModel::clearStockSelectionHistory,
                            onOpenStrategyCenter = { extraScreen = ScreenDestination.Strategy },
                        )

                        2 -> SignalsScreen(
                            snapshot = state.snapshot,
                            isRefreshing = state.isLoading,
                            message = state.message,
                            noticeType = state.noticeType,
                            onRefresh = viewModel::refreshDashboard,
                            onOpenStockDetail = { symbol -> viewModel.loadStockDetail(symbol, showNotice = true) },
                        )

                        3 -> TradesScreen(
                            snapshot = state.snapshot,
                            isRefreshing = state.isLoading,
                            message = state.message,
                            noticeType = state.noticeType,
                            tradeNotes = state.tradeNotes,
                            tradeReminders = state.tradeReminders,
                            manualTradeRecords = state.manualTradeRecords,
                            onRefresh = viewModel::refreshDashboard,
                            onAddTrade = viewModel::createVirtualTrade,
                            onUpdateTrade = viewModel::updateVirtualTrade,
                            onDeleteTrade = viewModel::deleteVirtualTradeOrWarn,
                            onSaveTradeNote = viewModel::saveTradeNote,
                            onSaveTradeReminder = viewModel::saveTradeReminder,
                            onAddManualSellRecord = viewModel::addManualSellRecord,
                        )

                        else -> OverviewScreen(
                            snapshot = state.snapshot,
                            isLoading = state.isLoading,
                            isActionRunning = state.isActionRunning,
                            runningAction = state.runningAction,
                            message = state.message,
                            noticeType = state.noticeType,
                            autoRefreshSecondsRemaining = state.autoRefreshSecondsRemaining,
                            lastSyncedAtLabel = state.lastSyncedAtLabel,
                            dataSourceLabel = state.dataSourceLabel,
                            networkStatusLabel = state.networkStatusLabel,
                            isUsingCachedData = state.isUsingCachedData,
                            onRefresh = viewModel::refreshDashboard,
                            onRunStockSelection = { viewModel.executeStockSelectionEnhanced(state.defaultStrategy) },
                            onGeneratePlan = { viewModel.executeAction("generate_plan") },
                            onOpenActions = { extraScreen = ScreenDestination.Actions },
                            onNavigateToCandidates = { selectedTab = 1 },
                            onNavigateToTrades = { selectedTab = 3 },
                        )
                    }
                }

                state.stockDetail?.let { detail ->
                    StockDetailSheet(detail = detail, onDismiss = { viewModel.clearStockDetail() })
                }
                if (state.isStockDetailLoading) {
                    val loadingSymbol = state.stockDetailLoadingSymbol ?: "--"
                    StockDetailSheet(
                        detail = com.quant.system.data.model.StockDetailPayload(
                            symbol = loadingSymbol,
                            name = "加载中",
                            actionSuggestion = "正在获取详情，请稍候...",
                            keyRisks = listOf("网络请求进行中"),
                        ),
                        onDismiss = { viewModel.clearStockDetail() },
                    )
                }
            }
            }
        }
    }
}
