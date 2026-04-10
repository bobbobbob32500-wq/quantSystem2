package com.quant.system.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.CandidatePool
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.ui.screen.StocksScreen
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.QuantSystemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class StocksScreenFlowTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun runSelection_shouldUseSelectedStrategy() {
        var capturedStrategy = ""
        composeRule.setContent {
            QuantSystemTheme {
                StocksScreen(
                    snapshot = DashboardSnapshot(candidatePool = CandidatePool(count = 0, topCandidates = emptyList())),
                    selectionHistory = emptyList(),
                    preferredStrategyKey = "secondary_launch",
                    selectedHistoryId = null,
                    historyFilterStrategy = "all",
                    monitorExpectedActive = false,
                    isActionRunning = false,
                    runningAction = null,
                    actionElapsedSeconds = 0,
                    selectionStatusLabel = "尚未执行选股",
                    selectionLastStrategyLabel = "--",
                    selectionLastUpdatedAtLabel = "--",
                    selectionLastCount = null,
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    onRefresh = {},
                    onRunStockSelection = { capturedStrategy = it },
                    onPushSelection = {},
                    onApplySelectionHistory = {},
                    onChangeHistoryFilterStrategy = {},
                    onDeleteSelectionHistory = {},
                    onClearSelectionHistory = {},
                    onOpenStockDetail = {},
                    onOpenStrategyCenter = {},
                )
            }
        }

        composeRule.onNodeWithText("突破策略").performClick()
        composeRule.onNodeWithText("执行选股").performClick()

        assertEquals("breakout", capturedStrategy)
    }

    @Test
    fun candidateCard_shouldShowStrategyAndReason() {
        val snapshot = DashboardSnapshot(
            candidatePool = CandidatePool(
                count = 1,
                topCandidates = listOf(
                    Candidate(
                        symbol = "600519",
                        name = "贵州茅台",
                        score = 88.6,
                        strategyProfile = "breakout",
                        triggerReason = "放量突破关键价位",
                        triggerPrice = 1688.0,
                        currentPrice = 1692.0,
                    ),
                ),
            ),
        )

        composeRule.setContent {
            QuantSystemTheme {
                StocksScreen(
                    snapshot = snapshot,
                    selectionHistory = emptyList(),
                    preferredStrategyKey = "secondary_launch",
                    selectedHistoryId = null,
                    historyFilterStrategy = "all",
                    monitorExpectedActive = true,
                    isActionRunning = false,
                    runningAction = null,
                    actionElapsedSeconds = 0,
                    selectionStatusLabel = "执行完成：选出 1 只",
                    selectionLastStrategyLabel = "突破策略",
                    selectionLastUpdatedAtLabel = "2026-04-07 10:00:00",
                    selectionLastCount = 1,
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    onRefresh = {},
                    onRunStockSelection = {},
                    onPushSelection = {},
                    onApplySelectionHistory = {},
                    onChangeHistoryFilterStrategy = {},
                    onDeleteSelectionHistory = {},
                    onClearSelectionHistory = {},
                    onOpenStockDetail = {},
                    onOpenStrategyCenter = {},
                )
            }
        }

        composeRule.onNodeWithText("选股状态").assertIsDisplayed()
        composeRule.onNodeWithText("贵州茅台").assertIsDisplayed()
        composeRule.onNodeWithText("入选原因：放量突破关键价位").assertIsDisplayed()
        composeRule.onNodeWithText("触发价 1688.00").assertIsDisplayed()
    }

    @Test
    fun clickCandidate_shouldOpenDetail() {
        var openedSymbol: String? = null
        val snapshot = DashboardSnapshot(
            candidatePool = CandidatePool(
                count = 1,
                topCandidates = listOf(
                    Candidate(
                        symbol = "000001",
                        name = "平安银行",
                        score = 75.0,
                        strategyProfile = "legacy",
                    ),
                ),
            ),
        )

        composeRule.setContent {
            QuantSystemTheme {
                StocksScreen(
                    snapshot = snapshot,
                    selectionHistory = emptyList(),
                    preferredStrategyKey = "legacy",
                    selectedHistoryId = null,
                    historyFilterStrategy = "all",
                    monitorExpectedActive = false,
                    isActionRunning = false,
                    runningAction = null,
                    actionElapsedSeconds = 0,
                    selectionStatusLabel = "执行完成：选出 1 只",
                    selectionLastStrategyLabel = "原策略",
                    selectionLastUpdatedAtLabel = "2026-04-07 10:01:00",
                    selectionLastCount = 1,
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    onRefresh = {},
                    onRunStockSelection = {},
                    onPushSelection = {},
                    onApplySelectionHistory = {},
                    onChangeHistoryFilterStrategy = {},
                    onDeleteSelectionHistory = {},
                    onClearSelectionHistory = {},
                    onOpenStockDetail = { openedSymbol = it },
                    onOpenStrategyCenter = {},
                )
            }
        }

        composeRule.onNodeWithText("平安银行").performClick()
        assertTrue(openedSymbol == "000001")
    }
}
