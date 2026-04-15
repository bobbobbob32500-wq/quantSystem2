package com.quant.system.ui.screen.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.quant.system.BuildConfig
import com.quant.system.core.NotificationHelper
import com.quant.system.data.model.ActionRecord
import com.quant.system.data.model.AnalyticsSummaryPayload
import com.quant.system.data.model.AppUpdatePayload
import com.quant.system.data.model.BackgroundTaskRecord
import com.quant.system.data.model.CandidatePool
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.ManualTradeRecord
import com.quant.system.data.model.StockSelectionHistoryRecord
import com.quant.system.data.model.StockDetailPayload
import com.quant.system.data.model.StrategyMeta
import com.quant.system.data.model.TradeReminderSetting
import com.quant.system.data.model.WatchlistPayload
import com.quant.system.data.model.AIStatus
import com.quant.system.data.model.ButlerStatus
import com.quant.system.data.model.AlertItem
import com.quant.system.data.model.AlertSummary
import com.quant.system.data.model.PriceAlertItem
import com.quant.system.data.model.WatcherSummary
import com.quant.system.data.model.DeepReviewResult
import com.quant.system.data.model.KnowledgeTopic
import com.quant.system.data.model.KnowledgeArticle
import com.quant.system.core.data.DataSyncOptimizer
import com.quant.system.core.performance.AppPerformanceOptimizer
import com.quant.system.core.stability.GlobalExceptionHandler
import com.quant.system.core.ux.PerformanceMonitor
import com.quant.system.core.ux.UserExperienceOptimizer
import com.quant.system.data.repository.AIRepository
import com.quant.system.data.repository.DashboardRepository
import com.quant.system.data.repository.LocalCacheRepository
import com.quant.system.data.repository.SelectionHistoryRepository
import com.quant.system.data.repository.SettingsRepository
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

enum class NoticeType { Success, Error, Info }
enum class NavigationTarget { Candidates, History }

data class DebugPanelState(
    val backendStatusLabel: String = "未检测",
    val backendServiceName: String = "--",
    val backendDocsUrl: String = "--",
    val lastCheckedAtLabel: String? = null,
    val contractStatusLabel: String = "未同步",
)

data class DashboardUiState(
    val snapshot: DashboardSnapshot? = null,
    val isLoading: Boolean = false,
    val message: String? = null,
    val noticeType: NoticeType = NoticeType.Info,
    val noticeVersion: Long = 0L,
    val currentBaseUrl: String = "",
    val baseUrlInput: String = "",
    val isSavingSettings: Boolean = false,
    val currentVersionName: String = BuildConfig.VERSION_NAME,
    val currentVersionCode: Int = BuildConfig.VERSION_CODE,
    val isCheckingUpdate: Boolean = false,
    val latestUpdate: AppUpdatePayload? = null,
    val highContrastEnabled: Boolean = false,
    val defaultStrategy: String = "secondary_launch",
    val homeModuleOrder: String = "overview,task,health,metrics,signals",
    val watchlist: WatchlistPayload = WatchlistPayload(),
    val isNotificationPermissionGranted: Boolean = false,
    val notifyHighPrioritySignalOnly: Boolean = false,
    val notifyActionCompleteEnabled: Boolean = true,
    val silentStart: String = "22:30",
    val silentEnd: String = "07:30",
    val signalPriorityKeywords: String = "buy,strong,breakout,突破,高优先",
    val notificationLogRetentionDays: Int = 7,
    val notificationLogs: List<String> = emptyList(),
    val debugPanel: DebugPanelState = DebugPanelState(),
    val actionHistory: List<ActionRecord> = emptyList(),
    val stockSelectionHistory: List<StockSelectionHistoryRecord> = emptyList(),
    val selectionHistoryFilterStrategy: String = "all",
    val activeSelectionHistoryId: Long? = null,
    val activeSelectionStrategyKey: String? = null,
    val selectionStatusLabel: String = "尚未执行选股",
    val selectionLastStrategyLabel: String = "--",
    val selectionLastUpdatedAtLabel: String = "--",
    val selectionLastCount: Int? = null,
    val monitorExpectedActive: Boolean = false,
    val backgroundTasks: List<BackgroundTaskRecord> = emptyList(),
    val isHistoryLoading: Boolean = false,
    val isActionRunning: Boolean = false,
    val runningAction: String? = null,
    val actionElapsedSeconds: Int = 0,
    val actionProgress: Float = 0f,
    val stockDetail: StockDetailPayload? = null,
    val isStockDetailLoading: Boolean = false,
    val stockDetailLoadingSymbol: String? = null,
    val strategies: List<StrategyMeta> = emptyList(),
    val analyticsSummary: AnalyticsSummaryPayload? = null,
    val tradeNotes: Map<String, String> = emptyMap(),
    val tradeReminders: Map<String, TradeReminderSetting> = emptyMap(),
    val manualTradeRecords: List<ManualTradeRecord> = emptyList(),
    val autoRefreshSecondsRemaining: Int = 30,
    val lastSyncedAtLabel: String = "--",
    val dataSourceLabel: String = "未同步",
    val networkStatusLabel: String = "网络状态：未检测",
    val isUsingCachedData: Boolean = false,
    val pendingNavigationTarget: NavigationTarget? = null,
    val navigationVersion: Long = 0L,
    // AI管家相关状态
    val aiAvailable: Boolean = false,
    val aiStatus: AIStatus? = null,
    val butlerStatus: ButlerStatus? = null,
    val aiMessages: List<ChatMessage> = emptyList(),
    val aiInputText: String = "",
    val isAiLoading: Boolean = false,
    // 扩展功能状态
    val activeAlerts: List<AlertItem> = emptyList(),
    val alertSummary: AlertSummary? = null,
    val watcherAlerts: List<PriceAlertItem> = emptyList(),
    val watcherSummary: WatcherSummary? = null,
    val deepReviewResult: DeepReviewResult? = null,
    val knowledgeTopics: List<KnowledgeTopic> = emptyList(),
    val knowledgeCategories: List<String> = emptyList(),
    val selectedKnowledgeArticle: KnowledgeArticle? = null,
)

class DashboardViewModel(application: Application) : AndroidViewModel(application) {
    private val repo = DashboardRepository(application)
    private val aiRepo = AIRepository(application)
    private val settings = SettingsRepository(application)
    private val cache = LocalCacheRepository(application)
    private val selectionHistoryRepo = SelectionHistoryRepository(application)
    private val notifier = NotificationHelper(application)
    private val dataSyncOptimizer = DataSyncOptimizer(application)
    private val performanceOptimizer = AppPerformanceOptimizer.getInstance(application)
    private val performanceMonitor = PerformanceMonitor(application)

    var uiState = DashboardUiState()
        private set

    private var autoRefreshJob: Job? = null
    private var historyJob: Job? = null
    private var actionTimerJob: Job? = null
    private var previousSignalKeys: Set<String> = emptySet()
    private var lastDashboardRefreshAtMs: Long = 0L
    private val dashboardRefreshMutex = Mutex()

    init {
        val baseUrl = settings.getBaseUrl()
        uiState = uiState.copy(
            currentBaseUrl = baseUrl,
            baseUrlInput = baseUrl,
            highContrastEnabled = settings.isHighContrastEnabled(),
            defaultStrategy = settings.getDefaultStrategy(),
            homeModuleOrder = settings.getHomeModuleOrder(),
            notifyHighPrioritySignalOnly = settings.isHighPrioritySignalOnlyEnabled(),
            notifyActionCompleteEnabled = settings.isActionCompleteNotifyEnabled(),
            silentStart = settings.getSilentStart(),
            silentEnd = settings.getSilentEnd(),
            signalPriorityKeywords = settings.getSignalPriorityKeywords(),
            notificationLogRetentionDays = settings.getNotificationLogRetentionDays(),
            notificationLogs = settings.getNotificationLogs(),
            isNotificationPermissionGranted = notifier.canPostNotifications(),
            activeSelectionStrategyKey = settings.getDefaultStrategy(),
            selectionStatusLabel = "就绪，可执行选股",
            selectionLastStrategyLabel = strategyLabelOf(settings.getDefaultStrategy()),
            selectionLastUpdatedAtLabel = "--",
            manualTradeRecords = settings.getManualTradeRecords(),
        )

        // 启用性能优化
        performanceOptimizer.enableOptimizations()
        
        // 跟踪ViewModel内存泄漏
        performanceOptimizer.trackViewModel(this)
        
        // 启动性能监控
        performanceMonitor.startMonitoring()

        viewModelScope.launch {
            loadLocalBootstrapData()
            refreshDashboardInternal(showNotice = false, force = true)
            refreshActionHistory(false)
            refreshStockSelectionHistory(false)
            refreshBackgroundTasks(false)
            refreshStrategies(false)
            refreshAnalyticsSummary(false)
            refreshWatchlist(false)
            refreshAIStatus(false)
        }
        setAutoRefreshEnabled(true)
    }

    fun refreshDashboard() = viewModelScope.launch { 
        recordUserInteraction("refresh_dashboard")
        refreshDashboardInternal(showNotice = false, force = true) 
    }
    fun refreshNotificationPermissionStatus() { uiState = uiState.copy(isNotificationPermissionGranted = notifier.canPostNotifications()) }
    fun onNotificationPermissionResult(granted: Boolean) { uiState = uiState.copy(isNotificationPermissionGranted = granted) }
    fun updateBaseUrlInput(value: String) { uiState = uiState.copy(baseUrlInput = value) }
    fun clearUpdateInfo() { uiState = uiState.copy(latestUpdate = null) }
    fun consumeNavigationEvent() { uiState = uiState.copy(pendingNavigationTarget = null) }
    fun clearStockDetail() {
        uiState = uiState.copy(
            stockDetail = null,
            isStockDetailLoading = false,
            stockDetailLoadingSymbol = null,
        )
    }

    fun executeStockSelection(strategy: String) {
        executeStockSelectionEnhanced(strategy)
    }

    fun executeStockSelectionEnhanced(strategy: String) {
        if (uiState.isActionRunning) {
            post("已有任务执行中，请稍候", NoticeType.Info)
            return
        }
        
        recordUserInteraction("execute_stock_selection")
        
        viewModelScope.launch {
            val payload = buildJsonObject { if (strategy.isNotBlank()) put("strategy", strategy) }
            val strategyLabel = strategyLabelOf(strategy)
            post("已发送选股命令（$strategyLabel），正在执行...", NoticeType.Info)

            uiState = uiState.copy(
                isActionRunning = true,
                runningAction = "run_stock_selection",
                actionElapsedSeconds = 0,
                actionProgress = 0.05f,
                selectionStatusLabel = "执行中...",
                selectionLastStrategyLabel = strategyLabel,
                selectionLastUpdatedAtLabel = nowLabel(),
            )
            startActionTimer(45_000L)

            val result = safeExecuteWithRetry("execute_stock_selection") {
                withTimeout(45_000L) {
                    repo.executeAction(
                        baseUrl = uiState.currentBaseUrl,
                        action = "run_stock_selection",
                        payload = payload,
                        confirmed = true,
                    ).getOrThrow()
                }
            }

            result.onSuccess {
                refreshDashboardInternal(showNotice = false, force = true)
                refreshActionHistory(false)
                refreshBackgroundTasks(false)
                val candidates = uiState.snapshot?.candidatePool?.topCandidates.orEmpty()
                withContext(Dispatchers.IO) {
                    selectionHistoryRepo.saveSelection(
                        strategyKey = strategy,
                        strategyLabel = strategyLabel,
                        candidates = candidates,
                    )
                }
                refreshStockSelectionHistory(false)
                uiState = uiState.copy(
                    activeSelectionHistoryId = null,
                    activeSelectionStrategyKey = strategy,
                )
                val count = uiState.snapshot?.candidatePool?.count ?: uiState.snapshot?.candidatePool?.topCandidates?.size ?: 0
                val statusLabel = if (count > 0) "执行完成：选出 $count 只" else "执行完成：未选出标的"
                uiState = uiState.copy(
                    selectionStatusLabel = statusLabel,
                    selectionLastCount = count,
                    selectionLastUpdatedAtLabel = nowLabel(),
                )
                if (count > 0) {
                    post("选股完成：当前候选池 $count 只", NoticeType.Success)
                } else {
                    post("选股已完成：当前无候选结果", NoticeType.Info)
                }
            }.onFailure { e ->
                if (e is kotlinx.coroutines.TimeoutCancellationException) {
                    post("选股请求超时，任务可能仍在后端执行，请稍后查看历史记录", NoticeType.Info)
                    uiState = uiState.copy(
                        selectionStatusLabel = "请求超时：可能仍在后端执行",
                        selectionLastUpdatedAtLabel = nowLabel(),
                    )
                    refreshActionHistory(false)
                } else {
                    uiState = uiState.copy(
                        selectionStatusLabel = "执行失败：${e.message ?: "未知错误"}",
                        selectionLastUpdatedAtLabel = nowLabel(),
                    )
                    post(e.message ?: "选股执行失败", NoticeType.Error)
                }
            }

            stopActionTimer()
            uiState = uiState.copy(
                isActionRunning = false,
                runningAction = null,
                actionProgress = 0f,
            )
        }
    }

    fun executeAction(action: String, payload: JsonObject? = null) {
        if (uiState.isActionRunning) return post("已有任务执行中，请稍候", NoticeType.Info)
        viewModelScope.launch {
            val timeoutMs = if (action in setOf("generate_plan", "generate_post_market_review")) 120_000L else 45_000L
            uiState = uiState.copy(isActionRunning = true, runningAction = action, actionElapsedSeconds = 0, actionProgress = 0.05f)
            startActionTimer(timeoutMs)
            val result = runCatching {
                withTimeout(timeoutMs) { repo.executeAction(uiState.currentBaseUrl, action, payload, true).getOrThrow() }
            }
            result.onSuccess {
                post(it.message ?: "动作已提交", NoticeType.Success)
                if (action == "start_monitor_runtime") {
                    uiState = uiState.copy(monitorExpectedActive = true)
                } else if (action == "stop_monitor_runtime") {
                    uiState = uiState.copy(monitorExpectedActive = false)
                }
                if (uiState.notifyActionCompleteEnabled && !isSilentNow()) {
                    notifier.notifyActionResult("动作完成", it.message ?: action)
                    appendLog("ACTION|$action|${it.message ?: "完成"}")
                }
                refreshActionHistory(false); refreshBackgroundTasks(false); refreshDashboardInternal(showNotice = false, force = true)
            }.onFailure { e ->
                if (e is kotlinx.coroutines.TimeoutCancellationException) {
                    post("任务可能仍在后端执行，请稍后在历史记录查看结果", NoticeType.Info)
                    refreshActionHistory(false)
                } else {
                    post(e.message ?: "动作执行失败", NoticeType.Error)
                }
            }
            stopActionTimer()
            uiState = uiState.copy(isActionRunning = false, runningAction = null, actionProgress = 0f)
        }
    }

    fun refreshActionHistory(showNotice: Boolean) = viewModelScope.launch {
        uiState = uiState.copy(isHistoryLoading = true)
        repo.getActionRecords(uiState.currentBaseUrl).onSuccess {
            withContext(Dispatchers.IO) {
                cache.saveActionRecords(it)
            }
            uiState = uiState.copy(actionHistory = it, isHistoryLoading = false)
            if (showNotice) post("历史已刷新", NoticeType.Success)
        }.onFailure { uiState = uiState.copy(isHistoryLoading = false); if (showNotice) post(it.message ?: "加载历史失败", NoticeType.Error) }
    }

    fun refreshBackgroundTasks(showNotice: Boolean) = viewModelScope.launch {
        repo.getBackgroundTasks(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(backgroundTasks = it); if (showNotice) post("任务状态已更新", NoticeType.Success)
        }.onFailure { if (showNotice) post(it.message ?: "加载任务失败", NoticeType.Error) }
    }

    fun refreshStockSelectionHistory(showNotice: Boolean) = viewModelScope.launch {
        val strategy = uiState.selectionHistoryFilterStrategy.takeUnless { it == "all" }
        val records = withContext(Dispatchers.IO) {
            selectionHistoryRepo.getRecentSelections(limit = 20, strategyKey = strategy)
        }
        uiState = uiState.copy(stockSelectionHistory = records)
        if (showNotice) {
            post("本地选股历史已更新", NoticeType.Success)
        }
    }

    fun setSelectionHistoryFilterStrategy(strategyKey: String) {
        val normalized = strategyKey.trim().ifBlank { "all" }
        uiState = uiState.copy(selectionHistoryFilterStrategy = normalized)
        refreshStockSelectionHistory(showNotice = false)
    }

    fun deleteStockSelectionHistory(recordId: Long) = viewModelScope.launch {
        if (recordId <= 0L) return@launch
        val deleted = withContext(Dispatchers.IO) {
            selectionHistoryRepo.deleteSelection(recordId)
        }
        if (!deleted) {
            post("删除失败，记录不存在", NoticeType.Error)
            return@launch
        }
        val clearSelected = if (uiState.activeSelectionHistoryId == recordId) null else uiState.activeSelectionHistoryId
        uiState = uiState.copy(activeSelectionHistoryId = clearSelected)
        refreshStockSelectionHistory(showNotice = false)
        post("历史记录已删除", NoticeType.Success)
    }

    fun clearStockSelectionHistory() = viewModelScope.launch {
        val count = withContext(Dispatchers.IO) {
            selectionHistoryRepo.clearAll()
        }
        uiState = uiState.copy(
            stockSelectionHistory = emptyList(),
            activeSelectionHistoryId = null,
        )
        post("已清空历史记录（$count 条）", NoticeType.Success)
    }

    fun applyStockSelectionHistory(recordId: Long) = viewModelScope.launch {
        val target = uiState.stockSelectionHistory.firstOrNull { it.id == recordId }
            ?: withContext(Dispatchers.IO) {
                selectionHistoryRepo.getRecentSelections(limit = 50).firstOrNull { it.id == recordId }
            }
            ?: run {
                post("未找到对应的历史选股记录", NoticeType.Error)
                return@launch
            }

        val snapshot = (uiState.snapshot ?: DashboardSnapshot()).copy(
            candidatePool = target.toCandidatePool(),
        )
        uiState = uiState.copy(
            snapshot = snapshot,
            activeSelectionHistoryId = target.id,
            activeSelectionStrategyKey = target.strategyKey,
            selectionStatusLabel = if (target.candidateCount > 0) {
                "已恢复历史：选出 ${target.candidateCount} 只"
            } else {
                "已恢复历史：该次未选出标的"
            },
            selectionLastStrategyLabel = target.strategyLabel,
            selectionLastCount = target.candidateCount,
            selectionLastUpdatedAtLabel = target.createdAtLabel,
            isUsingCachedData = true,
            dataSourceLabel = "本地选股历史",
            lastSyncedAtLabel = target.createdAtLabel,
        )
        post("已恢复 ${target.createdAtLabel} 的选股结果", NoticeType.Success)
    }

    fun retryBackgroundTask(taskId: String) = viewModelScope.launch {
        if (taskId.isBlank()) return@launch
        repo.retryBackgroundTask(uiState.currentBaseUrl, taskId).onSuccess {
            post("任务已重试", NoticeType.Success); refreshBackgroundTasks(false); refreshActionHistory(false)
        }.onFailure { post(it.message ?: "重试失败", NoticeType.Error) }
    }

    fun refreshStrategies(showNotice: Boolean) = viewModelScope.launch {
        repo.getStrategies(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(strategies = it); if (showNotice) post("策略列表已更新", NoticeType.Success)
        }.onFailure { if (showNotice) post(it.message ?: "加载策略失败", NoticeType.Error) }
    }

    fun runStrategy(strategyId: String, params: Map<String, Any?>) = viewModelScope.launch {
        if (strategyId.isBlank()) return@launch
        repo.runStrategy(uiState.currentBaseUrl, strategyId, params).onSuccess {
            post(it.message ?: "策略执行已提交", NoticeType.Success); refreshBackgroundTasks(false)
        }.onFailure { post(it.message ?: "策略执行失败", NoticeType.Error) }
    }

    fun refreshAnalyticsSummary(showNotice: Boolean) = viewModelScope.launch {
        repo.getAnalyticsSummary(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(analyticsSummary = it); if (showNotice) post("复盘统计已更新", NoticeType.Success)
        }.onFailure { if (showNotice) post(it.message ?: "加载复盘失败", NoticeType.Error) }
    }

    fun loadStockDetail(symbol: String, showNotice: Boolean) = viewModelScope.launch {
        if (symbol.isBlank()) return@launch
        val normalized = symbol.trim().uppercase(Locale.getDefault())
        uiState = uiState.copy(
            isStockDetailLoading = true,
            stockDetailLoadingSymbol = normalized,
        )
        if (showNotice) {
            post("正在加载 $normalized 详情...", NoticeType.Info)
        }
        val result = runCatching {
            withTimeout(12_000L) {
                repo.getStockDetail(uiState.currentBaseUrl, normalized).getOrThrow()
            }
        }
        result.onSuccess {
            uiState = uiState.copy(
                stockDetail = it,
                isStockDetailLoading = false,
                stockDetailLoadingSymbol = null,
            )
        }.onFailure { e ->
            uiState = uiState.copy(
                isStockDetailLoading = false,
                stockDetailLoadingSymbol = null,
            )
            if (e is kotlinx.coroutines.TimeoutCancellationException) {
                if (showNotice) post("加载个股详情超时，请稍后重试", NoticeType.Error)
            } else if (showNotice) {
                post(e.message ?: "加载个股详情失败", NoticeType.Error)
            }
        }
    }

    fun createVirtualTrade(symbol: String, name: String, buyPrice: Double, quantity: Int) = viewModelScope.launch {
        repo.createVirtualTrade(uiState.currentBaseUrl, symbol, name, buyPrice, quantity).onSuccess {
            post("持仓已新增", NoticeType.Success); refreshDashboardInternal(showNotice = false, force = true)
        }.onFailure { post(it.message ?: "新增持仓失败", NoticeType.Error) }
    }

    fun updateVirtualTrade(tradeId: String, symbol: String, name: String, buyPrice: Double, quantity: Int) = viewModelScope.launch {
        if (tradeId.isBlank()) return@launch
        repo.updateVirtualTrade(uiState.currentBaseUrl, tradeId, symbol, name, buyPrice, quantity).onSuccess {
            post("持仓已更新", NoticeType.Success); refreshDashboardInternal(showNotice = false, force = true)
        }.onFailure { post(it.message ?: "更新持仓失败", NoticeType.Error) }
    }

    fun deleteVirtualTrade(tradeId: String) = viewModelScope.launch {
        if (tradeId.isBlank()) return@launch
        repo.deleteVirtualTrade(uiState.currentBaseUrl, tradeId).onSuccess {
            post("持仓已删除", NoticeType.Success); refreshDashboardInternal(showNotice = false, force = true)
        }.onFailure { post(it.message ?: "删除持仓失败", NoticeType.Error) }
    }

    fun deleteVirtualTradeOrWarn(tradeId: String?) {
        val id = tradeId?.trim().orEmpty()
        if (id.isBlank()) {
            post("删除失败：该持仓缺少 trade_id，请先刷新数据后重试", NoticeType.Error)
            return
        }
        deleteVirtualTrade(id)
    }

    fun saveTradeNote(tradeId: String, note: String) {
        if (tradeId.isBlank()) return
        settings.setTradeNote(tradeId, note.trim())
        uiState = uiState.copy(tradeNotes = uiState.tradeNotes + (tradeId to note.trim()))
        post("备注已保存", NoticeType.Success)
    }

    fun saveTradeReminder(tradeId: String, stopLossPct: Double?, takeProfitPct: Double?) {
        if (tradeId.isBlank()) return
        val value = TradeReminderSetting(stopLossPct, takeProfitPct)
        settings.setTradeReminder(tradeId, value)
        uiState = uiState.copy(tradeReminders = uiState.tradeReminders + (tradeId to value))
        post("止盈止损已保存", NoticeType.Success)
    }

    fun addManualSellRecord(symbol: String, name: String, sellPrice: Double, quantity: Int, note: String?) {
        if (symbol.isBlank() || sellPrice <= 0.0 || quantity <= 0) return
        settings.appendManualTradeRecord(
            ManualTradeRecord(symbol, name.ifBlank { symbol }, "sell", sellPrice, quantity, nowLabel(), note?.trim()),
        )
        uiState = uiState.copy(
            manualTradeRecords = settings.getManualTradeRecords(),
            pendingNavigationTarget = NavigationTarget.History,
            navigationVersion = uiState.navigationVersion + 1L,
        )
        post("卖出记录已保存", NoticeType.Success)
    }

    fun sendTestNotification() {
        notifier.notifyTest()
        appendLog("TEST|发送测试通知")
        post("测试通知已发送", NoticeType.Success)
    }

    fun saveBaseUrl() {
        val raw = uiState.baseUrlInput.trim()
        if (raw.isBlank()) return post("API 地址不能为空", NoticeType.Error)
        val normalized = com.quant.system.data.api.RetrofitClient.normalizeBaseUrl(raw)
        settings.saveBaseUrl(normalized)
        uiState = uiState.copy(currentBaseUrl = normalized, baseUrlInput = normalized)
        post("API 地址已保存", NoticeType.Success)
        testConnection()
        refreshDashboard()
    }

    fun testConnection() = viewModelScope.launch {
        repo.checkHealth(uiState.currentBaseUrl).onSuccess { health ->
            repo.getRootInfo(uiState.currentBaseUrl).onSuccess { root ->
                uiState = uiState.copy(debugPanel = uiState.debugPanel.copy(
                    backendStatusLabel = "连接正常 (${health.status})",
                    backendServiceName = health.service,
                    backendDocsUrl = root.docs.ifBlank { "--" },
                    lastCheckedAtLabel = nowLabel(),
                    contractStatusLabel = "接口已同步",
                ))
                post("连接成功", NoticeType.Success)
            }.onFailure {
                uiState = uiState.copy(debugPanel = uiState.debugPanel.copy(
                    backendStatusLabel = "部分可用",
                    backendServiceName = health.service,
                    backendDocsUrl = "--",
                    lastCheckedAtLabel = nowLabel(),
                    contractStatusLabel = "文档获取失败",
                ))
                post("连接部分可用", NoticeType.Info)
            }
        }.onFailure {
            uiState = uiState.copy(debugPanel = uiState.debugPanel.copy(
                backendStatusLabel = "连接失败",
                backendServiceName = "--",
                backendDocsUrl = "--",
                lastCheckedAtLabel = nowLabel(),
                contractStatusLabel = "待联调",
            ))
            post(it.message ?: "连接失败", NoticeType.Error)
        }
    }

    fun checkForAppUpdate(showNoUpdateNotice: Boolean) = viewModelScope.launch {
        uiState = uiState.copy(isCheckingUpdate = true)
        repo.getAndroidLatestUpdate(uiState.currentBaseUrl).onSuccess {
            val available = it.available && (it.latestVersionCode ?: 0) > uiState.currentVersionCode && !it.apkUrl.isNullOrBlank()
            uiState = uiState.copy(isCheckingUpdate = false, latestUpdate = it.takeIf { _ -> available })
            if (available) post("发现新版本 ${it.latestVersionName ?: ""}", NoticeType.Success)
            else if (showNoUpdateNotice) post("当前已是最新版本", NoticeType.Info)
        }.onFailure { uiState = uiState.copy(isCheckingUpdate = false); post(it.message ?: "检查更新失败", NoticeType.Error) }
    }

    fun setHighContrastEnabled(enabled: Boolean) { settings.setHighContrastEnabled(enabled); uiState = uiState.copy(highContrastEnabled = enabled) }
    fun setDefaultStrategy(strategy: String) { val v = strategy.trim().ifBlank { "secondary_launch" }; settings.setDefaultStrategy(v); uiState = uiState.copy(defaultStrategy = v); post("默认策略已保存", NoticeType.Success) }
    fun setHomeModuleOrder(order: String) { val v = order.trim().ifBlank { "overview,task,health,metrics,signals" }; settings.setHomeModuleOrder(v); uiState = uiState.copy(homeModuleOrder = v); post("模块顺序已保存", NoticeType.Success) }
    fun setHighPrioritySignalOnly(enabled: Boolean) { settings.setHighPrioritySignalOnlyEnabled(enabled); uiState = uiState.copy(notifyHighPrioritySignalOnly = enabled) }
    fun setActionCompleteNotifyEnabled(enabled: Boolean) { settings.setActionCompleteNotifyEnabled(enabled); uiState = uiState.copy(notifyActionCompleteEnabled = enabled) }

    fun setSilentWindow(start: String, end: String) {
        if (!validTime(start) || !validTime(end)) return post("静默时段格式应为 HH:mm", NoticeType.Error)
        settings.setSilentStart(start); settings.setSilentEnd(end); uiState = uiState.copy(silentStart = start, silentEnd = end)
        post("静默时段已保存", NoticeType.Success)
    }

    fun setSignalPriorityKeywords(value: String) {
        settings.setSignalPriorityKeywords(value)
        uiState = uiState.copy(signalPriorityKeywords = settings.getSignalPriorityKeywords())
        post("关键词已保存", NoticeType.Success)
    }

    fun clearNotificationLogs() { settings.clearNotificationLogs(); uiState = uiState.copy(notificationLogs = emptyList()); post("通知日志已清空", NoticeType.Success) }

    fun setNotificationLogRetentionDays(days: Int) {
        val normalized = days.coerceIn(1, 30)
        settings.setNotificationLogRetentionDays(normalized)
        uiState = uiState.copy(
            notificationLogRetentionDays = normalized,
            notificationLogs = settings.getNotificationLogs(),
        )
        post("日志保留天数已更新", NoticeType.Success)
    }
    
    /**
     * 获取性能报告
     */
    suspend fun getPerformanceReport(): com.quant.system.core.ux.PerformanceReport {
        return performanceMonitor.getPerformanceReport()
    }
    
    /**
     * 导出性能数据
     */
    suspend fun exportPerformanceData(): java.io.File {
        return performanceMonitor.exportDataToFile()
    }
    
    /**
     * 重置性能数据
     */
    fun resetPerformanceData() {
        performanceMonitor.resetData()
        post("性能数据已重置", NoticeType.Success)
    }
    
    /**
     * 记录用户交互
     */
    fun recordUserInteraction(interactionType: String) {
        performanceMonitor.recordUserInteraction(interactionType)
    }
    
    /**
     * 记录操作性能
     */
    fun recordOperationPerformance(operationName: String, durationMs: Long) {
        performanceMonitor.recordOperationPerformance(operationName, durationMs)
    }
    
    /**
     * 记录网络请求时间
     */
    fun recordNetworkRequestTime(endpoint: String, requestTimeMs: Long) {
        performanceMonitor.recordNetworkRequestTime(endpoint, requestTimeMs)
    }
    
    /**
     * 记录UI渲染时间
     */
    fun recordUIRenderTime(screenName: String, renderTimeMs: Long) {
        performanceMonitor.recordUIRenderTime(screenName, renderTimeMs)
    }
    
    /**
     * 记录错误
     */
    fun recordError(errorType: String) {
        performanceMonitor.recordError(errorType)
        GlobalExceptionHandler.logError(errorType, null)
    }
    
    /**
     * 安全执行操作（带错误处理）
     */
    suspend fun <T> safeExecute(
        operationName: String,
        block: suspend () -> T
    ): Result<T> {
        val startTime = System.currentTimeMillis()
        return try {
            val result = block()
            val duration = System.currentTimeMillis() - startTime
            recordOperationPerformance(operationName, duration)
            Result.success(result)
        } catch (e: Exception) {
            val duration = System.currentTimeMillis() - startTime
            recordOperationPerformance("${operationName}_error", duration)
            recordError("${operationName}_${e::class.simpleName}")
            GlobalExceptionHandler.handleException(e, "ViewModel操作: $operationName")
            Result.failure(e)
        }
    }
    
    /**
     * 带重试的安全执行
     */
    suspend fun <T> safeExecuteWithRetry(
        operationName: String,
        maxRetries: Int = 3,
        initialDelay: Long = 1000L,
        block: suspend () -> T
    ): Result<T> {
        var lastError: Throwable? = null
        var delayMs = initialDelay
        
        repeat(maxRetries) { attempt ->
            val result = safeExecute("${operationName}_attempt_${attempt + 1}", block)
            if (result.isSuccess) {
                return result
            }
            
            lastError = result.exceptionOrNull()
            if (attempt < maxRetries - 1) {
                kotlinx.coroutines.delay(delayMs)
                delayMs *= 2 // 指数退避
            }
        }
        
        return Result.failure(lastError ?: Exception("操作失败: $operationName"))
    }

    fun updateWatchlist(symbols: List<String>) = viewModelScope.launch {
        val normalized = symbols.map { it.trim().uppercase(Locale.getDefault()) }.filter { it.isNotBlank() }.distinct()
        repo.updateWatchlist(uiState.currentBaseUrl, normalized).onSuccess {
            uiState = uiState.copy(watchlist = it); post("自选池已保存", NoticeType.Success)
        }.onFailure { post(it.message ?: "保存自选池失败", NoticeType.Error) }
    }

    fun setAutoRefreshEnabled(enabled: Boolean) {
        autoRefreshJob?.cancel()
        if (!enabled) return
        autoRefreshJob = viewModelScope.launch {
            var remain = 30
            while (isActive) {
                uiState = uiState.copy(autoRefreshSecondsRemaining = remain)
                delay(1_000L)
                remain -= 1
                if (remain <= 0) {
                    if (!uiState.isActionRunning) {
                        refreshDashboardInternal(false)
                    }
                    remain = 30
                }
            }
        }
    }

    fun startHistoryLivePolling() {
        historyJob?.cancel()
        historyJob = viewModelScope.launch {
            while (isActive) { refreshBackgroundTasks(false); delay(5_000L) }
        }
    }

    fun stopHistoryLivePolling() { historyJob?.cancel(); historyJob = null }

    private suspend fun refreshDashboardInternal(showNotice: Boolean, force: Boolean = false) {
        val now = System.currentTimeMillis()
        if (!force && now - lastDashboardRefreshAtMs < DASHBOARD_REFRESH_MIN_INTERVAL_MS) {
            return
        }
        dashboardRefreshMutex.withLock {
            val lockedNow = System.currentTimeMillis()
            if (!force && lockedNow - lastDashboardRefreshAtMs < DASHBOARD_REFRESH_MIN_INTERVAL_MS) {
                return@withLock
            }
            lastDashboardRefreshAtMs = lockedNow
            uiState = uiState.copy(isLoading = true)
            
            val startTime = System.currentTimeMillis()
            
            // 使用数据同步优化器进行智能同步
            dataSyncOptimizer.startSync(
                baseUrl = uiState.currentBaseUrl,
                onSuccess = { snapshot ->
                    val duration = System.currentTimeMillis() - startTime
                    recordNetworkRequestTime("dashboard_sync", duration)
                    
                    viewModelScope.launch {
                        val snapshotWithFallback = withContext(Dispatchers.IO) {
                            withLocalSelectionFallback(snapshot)
                        }
                        withContext(Dispatchers.IO) {
                            cache.saveDashboardSnapshot(snapshotWithFallback)
                        }
                        uiState = uiState.copy(
                            snapshot = snapshotWithFallback,
                            isLoading = false,
                            isUsingCachedData = false,
                            dataSourceLabel = "实时数据",
                            networkStatusLabel = "网络状态：正常",
                            lastSyncedAtLabel = snapshotWithFallback.meta?.generatedLabel ?: nowLabel(),
                            tradeNotes = buildTradeNotes(snapshotWithFallback),
                            tradeReminders = buildTradeReminders(snapshotWithFallback),
                            monitorExpectedActive = snapshotWithFallback.monitorSession?.isActive
                                ?: uiState.monitorExpectedActive,
                        )
                        notifySignals(snapshotWithFallback)
                        if (showNotice) post("数据已刷新 (${duration}ms)", NoticeType.Success)
                    }
                },
                onError = { error ->
                    val duration = System.currentTimeMillis() - startTime
                    recordNetworkRequestTime("dashboard_sync_error", duration)
                    recordError("dashboard_sync_failed")
                    
                    viewModelScope.launch {
                        val cached = withContext(Dispatchers.IO) { cache.getDashboardSnapshot() }
                        if (cached != null) {
                            uiState = uiState.copy(
                                snapshot = cached, isLoading = false, isUsingCachedData = true, dataSourceLabel = "本地缓存",
                                networkStatusLabel = if ((error.message ?: "").contains("超时")) "网络状态：较慢（已切缓存）" else "网络状态：异常（已切缓存）",
                                lastSyncedAtLabel = withContext(Dispatchers.IO) { cache.getDashboardCachedAt() }?.let(::formatMillis) ?: "--",
                            )
                            if (showNotice) post("网络异常，已使用缓存 (${duration}ms)", NoticeType.Info)
                        } else {
                            uiState = uiState.copy(
                                isLoading = false,
                                networkStatusLabel = if ((error.message ?: "").contains("超时")) "网络状态：较慢" else "网络状态：离线",
                            )
                            post("${error.message ?: "加载失败"} (${duration}ms)", NoticeType.Error)
                        }
                    }
                },
                forceRefresh = force
            )
        }
    }

    private fun refreshWatchlist(showNotice: Boolean) = viewModelScope.launch {
        repo.getWatchlist(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(watchlist = it)
            if (showNotice) post("自选池已同步", NoticeType.Success)
        }.onFailure { if (showNotice) post(it.message ?: "同步自选池失败", NoticeType.Error) }
    }

    private fun notifySignals(snapshot: DashboardSnapshot) {
        val items = snapshot.signals?.latestItems.orEmpty()
        val current = items.mapNotNull { it.tsCode?.let { code -> "$code|${it.signalTime.orEmpty()}|${it.signalType.orEmpty()}" } }.toSet()
        val news = items.filter {
            val code = it.tsCode ?: return@filter false
            "$code|${it.signalTime.orEmpty()}|${it.signalType.orEmpty()}" !in previousSignalKeys
        }
        if (news.isNotEmpty() && uiState.isNotificationPermissionGranted && !isSilentNow()) {
            val finalNews = if (uiState.notifyHighPrioritySignalOnly) filterByKeywords(news) else news
            finalNews.firstOrNull()?.let {
                val title = "新信号 ${it.tsCode.orEmpty()}"
                val content = it.triggerReason ?: it.suggestion ?: it.signalType ?: "有新的交易信号"
                notifier.notifySignalUpdate(title, content)
                appendLog("SIGNAL|$title|$content")
            }
        }
        previousSignalKeys = current
    }

    private fun filterByKeywords(items: List<com.quant.system.data.model.SignalItem>): List<com.quant.system.data.model.SignalItem> {
        val keys = uiState.signalPriorityKeywords.split(",").map { it.trim().lowercase(Locale.getDefault()) }.filter { it.isNotBlank() }
        if (keys.isEmpty()) return items
        return items.filter { s ->
            val text = "${s.signalType.orEmpty()} ${s.triggerReason.orEmpty()} ${s.suggestion.orEmpty()}".lowercase(Locale.getDefault())
            keys.any { text.contains(it) }
        }
    }

    private fun startActionTimer(timeoutMs: Long) {
        actionTimerJob?.cancel()
        actionTimerJob = viewModelScope.launch {
            val total = (timeoutMs / 1000L).toInt().coerceAtLeast(1)
            var elapsed = 0
            while (isActive && uiState.isActionRunning) {
                delay(1_000L); elapsed += 1
                uiState = uiState.copy(actionElapsedSeconds = elapsed, actionProgress = (elapsed.toFloat() / total).coerceAtMost(0.95f))
            }
        }
    }

    private fun stopActionTimer() { actionTimerJob?.cancel(); actionTimerJob = null; uiState = uiState.copy(actionElapsedSeconds = 0) }
    private fun appendLog(v: String) { settings.appendNotificationLog(v); uiState = uiState.copy(notificationLogs = settings.getNotificationLogs()) }
    private fun post(msg: String, type: NoticeType) { uiState = uiState.copy(message = msg, noticeType = type, noticeVersion = uiState.noticeVersion + 1) }
    private fun validTime(v: String): Boolean = runCatching { LocalTime.parse(v, DateTimeFormatter.ofPattern("HH:mm")) }.isSuccess
    private fun nowLabel(): String = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    private fun formatMillis(v: Long): String = runCatching { java.time.Instant.ofEpochMilli(v).atZone(java.time.ZoneId.systemDefault()).toLocalDateTime().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")) }.getOrDefault("--")

    private fun isSilentNow(): Boolean {
        val start = runCatching { LocalTime.parse(uiState.silentStart, DateTimeFormatter.ofPattern("HH:mm")) }.getOrNull() ?: return false
        val end = runCatching { LocalTime.parse(uiState.silentEnd, DateTimeFormatter.ofPattern("HH:mm")) }.getOrNull() ?: return false
        val now = LocalTime.now()
        return if (start <= end) now in start..end else now >= start || now <= end
    }

    private fun buildTradeNotes(snapshot: DashboardSnapshot?): Map<String, String> =
        snapshot?.virtualTrades?.openTrades.orEmpty().mapNotNull { t -> t.tradeId?.let { id -> id to settings.getTradeNote(id) } }.toMap()

    private fun buildTradeReminders(snapshot: DashboardSnapshot?): Map<String, TradeReminderSetting> =
        snapshot?.virtualTrades?.openTrades.orEmpty().mapNotNull { t -> t.tradeId?.let { id -> id to settings.getTradeReminder(id) } }.toMap()

    private suspend fun loadLocalBootstrapData() {
        val snapshot = withContext(Dispatchers.IO) {
            withLocalSelectionFallbackOrNull(cache.getDashboardSnapshot())
        }
        val localSelectionHistory = withContext(Dispatchers.IO) {
            selectionHistoryRepo.getRecentSelections(limit = 20)
        }
        val actionRecords = withContext(Dispatchers.IO) {
            cache.getActionRecords()
        }
        val cachedAt = withContext(Dispatchers.IO) {
            cache.getDashboardCachedAt()
        }

        uiState = uiState.copy(
            snapshot = snapshot,
            actionHistory = actionRecords,
            stockSelectionHistory = localSelectionHistory,
            selectionLastCount = snapshot?.candidatePool?.count ?: snapshot?.candidatePool?.topCandidates?.size,
            monitorExpectedActive = snapshot?.monitorSession?.isActive == true,
            isUsingCachedData = snapshot != null,
            dataSourceLabel = if (snapshot != null) "本地缓存" else "未同步",
            networkStatusLabel = if (snapshot != null) "网络状态：离线缓存" else "网络状态：未检测",
            lastSyncedAtLabel = cachedAt?.let(::formatMillis) ?: "--",
            tradeNotes = buildTradeNotes(snapshot),
            tradeReminders = buildTradeReminders(snapshot),
        )
        previousSignalKeys = snapshot.toSignalKeys()
    }

    private fun withLocalSelectionFallbackOrNull(snapshot: DashboardSnapshot?): DashboardSnapshot? {
        return snapshot?.let { withLocalSelectionFallback(it) }
    }

    private fun withLocalSelectionFallback(snapshot: DashboardSnapshot): DashboardSnapshot {
        val hasCandidates = snapshot.candidatePool?.topCandidates?.isNotEmpty() == true
        if (hasCandidates) return snapshot

        val latest = selectionHistoryRepo.getLatestWithCandidates() ?: return snapshot
        return snapshot.copy(candidatePool = latest.toCandidatePool())
    }

    private fun StockSelectionHistoryRecord.toCandidatePool(): CandidatePool {
        val avgScore = candidates.mapNotNull { it.score }.takeIf { it.isNotEmpty() }?.average()
        return CandidatePool(
            count = candidateCount,
            avgScore = avgScore,
            freshnessLabel = "本地记录 ${createdAtLabel}",
            topCandidates = candidates,
        )
    }

    private fun strategyLabelOf(strategy: String): String {
        return when (strategy) {
            "secondary_launch" -> "二次启动"
            "legacy" -> "原策略"
            "breakout" -> "突破策略"
            "both" -> "融合策略"
            else -> strategy.ifBlank { "默认策略" }
        }
    }

    private fun DashboardSnapshot?.toSignalKeys(): Set<String> =
        this?.signals?.latestItems.orEmpty().mapNotNull { it.tsCode?.let { c -> "$c|${it.signalTime.orEmpty()}|${it.signalType.orEmpty()}" } }.toSet()

    override fun onCleared() {
        autoRefreshJob?.cancel()
        historyJob?.cancel()
        actionTimerJob?.cancel()
        performanceMonitor.stopMonitoring()
        super.onCleared()
    }

    private companion object {
        const val DASHBOARD_REFRESH_MIN_INTERVAL_MS = 2_500L
    }
    
    // ==================== AI管家相关方法 ====================
    
    /**
     * 刷新AI服务状态
     */
    private fun refreshAIStatus(showNotice: Boolean) = viewModelScope.launch {
        // 获取AI服务状态
        aiRepo.getAIStatus(uiState.currentBaseUrl).onSuccess { status ->
            uiState = uiState.copy(
                aiAvailable = status.available,
                aiStatus = status,
            )
        }.onFailure {
            uiState = uiState.copy(aiAvailable = false)
            if (showNotice) post("AI服务不可用", NoticeType.Info)
        }
        
        // 获取管家状态
        aiRepo.getButlerStatus(uiState.currentBaseUrl).onSuccess { status ->
            uiState = uiState.copy(butlerStatus = status)
        }.onFailure {
            // 忽略管家状态获取失败
        }
    }
    
    /**
     * 发送AI消息
     */
    fun sendAIMessage(message: String) = viewModelScope.launch {
        if (message.isBlank()) return@launch
        if (uiState.isAiLoading) {
            post("AI正在思考中，请稍候", NoticeType.Info)
            return@launch
        }
        
        // 添加用户消息
        val userMessage = ChatMessage(role = "user", content = message)
        val loadingMessage = ChatMessage(role = "assistant", content = "", isLoading = true)
        uiState = uiState.copy(
            aiMessages = uiState.aiMessages + userMessage + loadingMessage,
            aiInputText = "",
            isAiLoading = true,
        )
        
        // 调用AI对话
        aiRepo.aiChat(uiState.currentBaseUrl, message).onSuccess { response ->
            val assistantMessage = ChatMessage(role = "assistant", content = response)
            uiState = uiState.copy(
                aiMessages = uiState.aiMessages.dropLast(1) + assistantMessage,
                isAiLoading = false,
            )
        }.onFailure { e ->
            val errorMessage = ChatMessage(
                role = "system",
                content = "AI响应失败: ${e.message ?: "未知错误"}"
            )
            uiState = uiState.copy(
                aiMessages = uiState.aiMessages.dropLast(1) + errorMessage,
                isAiLoading = false,
            )
            post(e.message ?: "AI对话失败", NoticeType.Error)
        }
    }
    
    /**
     * 快速预设问答
     */
    fun aiQuickAsk(key: String) = viewModelScope.launch {
        if (uiState.isAiLoading) {
            post("AI正在思考中，请稍候", NoticeType.Info)
            return@launch
        }
        
        val userMessage = ChatMessage(role = "user", content = key)
        val loadingMessage = ChatMessage(role = "assistant", content = "", isLoading = true)
        uiState = uiState.copy(
            aiMessages = uiState.aiMessages + userMessage + loadingMessage,
            isAiLoading = true,
        )
        
        aiRepo.aiQuickAsk(uiState.currentBaseUrl, key).onSuccess { response ->
            val assistantMessage = ChatMessage(role = "assistant", content = response)
            uiState = uiState.copy(
                aiMessages = uiState.aiMessages.dropLast(1) + assistantMessage,
                isAiLoading = false,
            )
        }.onFailure { e ->
            val errorMessage = ChatMessage(
                role = "system",
                content = "快速问答失败: ${e.message ?: "未知错误"}"
            )
            uiState = uiState.copy(
                aiMessages = uiState.aiMessages.dropLast(1) + errorMessage,
                isAiLoading = false,
            )
            post(e.message ?: "快速问答失败", NoticeType.Error)
        }
    }
    
    /**
     * 启动管家服务
     */
    fun startButler() = viewModelScope.launch {
        aiRepo.startButler(uiState.currentBaseUrl).onSuccess {
            post(it, NoticeType.Success)
            refreshAIStatus(false)
        }.onFailure { e ->
            post(e.message ?: "启动管家失败", NoticeType.Error)
        }
    }
    
    /**
     * 停止管家服务
     */
    fun stopButler() = viewModelScope.launch {
        aiRepo.stopButler(uiState.currentBaseUrl).onSuccess {
            post(it, NoticeType.Success)
            refreshAIStatus(false)
        }.onFailure { e ->
            post(e.message ?: "停止管家失败", NoticeType.Error)
        }
    }
    
    /**
     * 更新AI输入文本
     */
    fun updateAIInputText(text: String) {
        uiState = uiState.copy(aiInputText = text)
    }
    
    /**
     * 清空AI对话历史
     */
    fun clearAIHistory() {
        uiState = uiState.copy(aiMessages = emptyList())
        post("对话历史已清空", NoticeType.Success)
    }
    
    // ==================== 扩展功能方法 ====================
    
    /** 刷新预警 */
    fun refreshAlerts(showNotice: Boolean) = viewModelScope.launch {
        repo.getActiveAlerts(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(activeAlerts = it)
        }.onFailure { if (showNotice) post(it.message ?: "加载预警失败", NoticeType.Error) }
        repo.getAlertSummary(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(alertSummary = it)
        }
    }
    
    /** 确认预警 */
    fun ackAlert(alertId: String) = viewModelScope.launch {
        repo.ackAlert(uiState.currentBaseUrl, alertId).onSuccess {
            post("预警已确认", NoticeType.Success)
            refreshAlerts(false)
        }.onFailure { post(it.message ?: "确认失败", NoticeType.Error) }
    }
    
    /** 刷新盯盘提醒 */
    fun refreshWatcherAlerts(showNotice: Boolean) = viewModelScope.launch {
        repo.getWatcherAlerts(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(watcherAlerts = it)
        }.onFailure { if (showNotice) post(it.message ?: "加载盯盘失败", NoticeType.Error) }
        repo.getWatcherSummary(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(watcherSummary = it)
        }
    }
    
    /** 移除盯盘提醒 */
    fun removeWatcherAlert(alertId: String) = viewModelScope.launch {
        repo.removeWatcherAlert(uiState.currentBaseUrl, alertId).onSuccess {
            post("提醒已移除", NoticeType.Success)
            refreshWatcherAlerts(false)
        }.onFailure { post(it.message ?: "移除失败", NoticeType.Error) }
    }
    
    /** 执行深度复盘 */
    fun executeDeepReview() = viewModelScope.launch {
        val trades = uiState.snapshot?.virtualTrades?.closedTrades?.map { mapOf(
            "symbol" to (it.symbol ?: ""),
            "name" to (it.name ?: ""),
            "pnl_pct" to (it.pnlPct?.toString() ?: "0"),
            "hold_days" to "1",
        ) } ?: emptyList()
        repo.deepReview(uiState.currentBaseUrl, trades).onSuccess {
            uiState = uiState.copy(deepReviewResult = it)
            post("深度复盘完成", NoticeType.Success)
        }.onFailure { post(it.message ?: "深度复盘失败", NoticeType.Error) }
    }
    
    /** 刷新知识库主题 */
    fun refreshKnowledgeTopics(showNotice: Boolean) = viewModelScope.launch {
        repo.listKnowledgeTopics(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(knowledgeTopics = it)
        }.onFailure { if (showNotice) post(it.message ?: "加载知识库失败", NoticeType.Error) }
        repo.getKnowledgeCategories(uiState.currentBaseUrl).onSuccess {
            uiState = uiState.copy(knowledgeCategories = it)
        }
    }
    
    /** 查询知识 */
    fun queryKnowledge(topic: String) = viewModelScope.launch {
        repo.queryKnowledge(uiState.currentBaseUrl, topic).onSuccess {
            uiState = uiState.copy(selectedKnowledgeArticle = it)
        }.onFailure { post(it.message ?: "查询失败", NoticeType.Error) }
    }
}
