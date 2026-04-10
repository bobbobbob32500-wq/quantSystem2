package com.quant.system.ui.screen

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.PlaylistAddCheck
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.QueryStats
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.core.app.ActivityCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.quant.system.ui.screen.viewmodel.DashboardViewModel
import com.quant.system.ui.screen.viewmodel.DashboardViewModelFactory
import com.quant.system.ui.screen.viewmodel.NavigationTarget
import com.quant.system.ui.theme.Background
import com.quant.system.ui.theme.QuantSystemTheme
import kotlinx.coroutines.launch

private enum class ScreenDestination(val title: String) {
    Actions("动作中心"),
    History("执行历史"),
    Settings("设置"),
    Strategy("策略中心"),
    Analytics("复盘统计"),
    NotificationLogs("通知日志"),
}

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

    LaunchedEffect(extraScreen, selectedTab) {
        val shouldAutoRefreshOverview = extraScreen == null && selectedTab == 0
        viewModel.setAutoRefreshEnabled(shouldAutoRefreshOverview)
        if (shouldAutoRefreshOverview && !wasOverviewVisible) {
            viewModel.refreshDashboard()
        }
        wasOverviewVisible = shouldAutoRefreshOverview
        if (extraScreen == ScreenDestination.Settings) {
            viewModel.refreshNotificationPermissionStatus()
        }
        if (extraScreen == ScreenDestination.History) {
            viewModel.startHistoryLivePolling()
        } else {
            viewModel.stopHistoryLivePolling()
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
        else -> "量化移动端"
    }

    QuantSystemTheme(highContrast = state.highContrastEnabled) {
        Scaffold(
            snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
            topBar = {
                TopAppBar(
                    title = { Text(title) },
                    navigationIcon = if (extraScreen != null) {
                        {
                            IconButton(onClick = { extraScreen = null }) {
                                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                            }
                        }
                    } else {
                        {}
                    },
                    actions = {
                        if (extraScreen == null) {
                            IconButton(onClick = { extraScreen = ScreenDestination.History }) {
                                Icon(Icons.Filled.History, contentDescription = "执行历史")
                            }
                            IconButton(onClick = { extraScreen = ScreenDestination.Analytics }) {
                                Icon(Icons.Filled.Analytics, contentDescription = "复盘统计")
                            }
                            IconButton(onClick = { extraScreen = ScreenDestination.Settings }) {
                                Icon(Icons.Filled.Settings, contentDescription = "设置")
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(),
                )
            },
            bottomBar = {
                if (extraScreen == null) {
                    NavigationBar {
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
                            val intent = Intent(context, OptimizationTestActivity::class.java)
                            context.startActivity(intent)
                        },
                        onOpenOptimizationReport = {
                            val intent = Intent(context, OptimizationReportActivity::class.java)
                            context.startActivity(intent)
                        },
                        onOpenOptimizationLauncher = {
                            val intent = Intent(context, com.quant.system.core.test.OptimizationLauncherActivity::class.java)
                            context.startActivity(intent)
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
                            actionElapsedSeconds = state.actionElapsedSeconds,
                            selectionStatusLabel = state.selectionStatusLabel,
                            selectionLastStrategyLabel = state.selectionLastStrategyLabel,
                            selectionLastUpdatedAtLabel = state.selectionLastUpdatedAtLabel,
                            selectionLastCount = state.selectionLastCount,
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
                            onOpenStockDetail = { symbol -> viewModel.loadStockDetail(symbol, showNotice = true) },
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
