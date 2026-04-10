package com.quant.system.ui

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.quant.system.data.model.DashboardSnapshot
import com.quant.system.data.model.Trade
import com.quant.system.data.model.VirtualTrades
import com.quant.system.ui.screen.TradesScreen
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.QuantSystemTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class TradesScreenDeleteFlowTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun deleteTrade_shouldShowConfirmDialog_andCancelShouldNotInvokeCallback() {
        var callbackCount = 0
        composeRule.setContent {
            QuantSystemTheme {
                TradesScreen(
                    snapshot = DashboardSnapshot(
                        virtualTrades = VirtualTrades(
                            openCount = 1,
                            openTrades = listOf(
                                Trade(
                                    tradeId = "t-001",
                                    symbol = "600519",
                                    name = "贵州茅台",
                                    buyPrice = 1680.0,
                                    lastPrice = 1692.0,
                                ),
                            ),
                        ),
                    ),
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    tradeNotes = emptyMap(),
                    tradeReminders = emptyMap(),
                    manualTradeRecords = emptyList(),
                    onRefresh = {},
                    onAddTrade = { _, _, _, _ -> },
                    onUpdateTrade = { _, _, _, _, _ -> },
                    onDeleteTrade = { callbackCount += 1 },
                    onSaveTradeNote = { _, _ -> },
                    onSaveTradeReminder = { _, _, _ -> },
                    onAddManualSellRecord = { _, _, _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithText("删除").performClick()
        composeRule.onNodeWithText("确认删除持仓").assertIsDisplayed()
        composeRule.onNodeWithText("取消").performClick()
        composeRule.onAllNodesWithText("确认删除持仓").assertCountEquals(0)
        assertEquals(0, callbackCount)
    }

    @Test
    fun deleteTrade_shouldInvokeCallbackWithTradeId_whenConfirmed() {
        var capturedTradeId: String? = null
        composeRule.setContent {
            QuantSystemTheme {
                TradesScreen(
                    snapshot = DashboardSnapshot(
                        virtualTrades = VirtualTrades(
                            openCount = 1,
                            openTrades = listOf(
                                Trade(
                                    tradeId = "trade-888",
                                    symbol = "000001",
                                    name = "平安银行",
                                    buyPrice = 12.5,
                                    lastPrice = 12.7,
                                ),
                            ),
                        ),
                    ),
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    tradeNotes = emptyMap(),
                    tradeReminders = emptyMap(),
                    manualTradeRecords = emptyList(),
                    onRefresh = {},
                    onAddTrade = { _, _, _, _ -> },
                    onUpdateTrade = { _, _, _, _, _ -> },
                    onDeleteTrade = { capturedTradeId = it },
                    onSaveTradeNote = { _, _ -> },
                    onSaveTradeReminder = { _, _, _ -> },
                    onAddManualSellRecord = { _, _, _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithText("删除").performClick()
        composeRule.onNodeWithText("确认删除").performClick()
        assertEquals("trade-888", capturedTradeId)
    }

    @Test
    fun deleteTrade_shouldPassNull_whenTradeIdMissing() {
        var capturedTradeId: String? = "init"
        composeRule.setContent {
            QuantSystemTheme {
                TradesScreen(
                    snapshot = DashboardSnapshot(
                        virtualTrades = VirtualTrades(
                            openCount = 1,
                            openTrades = listOf(
                                Trade(
                                    tradeId = null,
                                    symbol = "300750",
                                    name = "宁德时代",
                                    buyPrice = 210.0,
                                    lastPrice = 208.0,
                                ),
                            ),
                        ),
                    ),
                    isRefreshing = false,
                    message = null,
                    noticeType = NoticeType.Info,
                    tradeNotes = emptyMap(),
                    tradeReminders = emptyMap(),
                    manualTradeRecords = emptyList(),
                    onRefresh = {},
                    onAddTrade = { _, _, _, _ -> },
                    onUpdateTrade = { _, _, _, _, _ -> },
                    onDeleteTrade = { capturedTradeId = it },
                    onSaveTradeNote = { _, _ -> },
                    onSaveTradeReminder = { _, _, _ -> },
                    onAddManualSellRecord = { _, _, _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithText("删除").performClick()
        composeRule.onNodeWithText("确认删除").performClick()
        assertTrue(capturedTradeId == null)
        assertNull(capturedTradeId)
    }
}
