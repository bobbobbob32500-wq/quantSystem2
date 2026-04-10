package com.quant.system.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.quant.system.ui.screen.ActionsScreen
import com.quant.system.ui.theme.QuantSystemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ActionsScreenExecutionStateTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun runningState_shouldShowProgressAndDisableRefresh() {
        composeRule.setContent {
            QuantSystemTheme {
                ActionsScreen(
                    isActionRunning = true,
                    runningAction = "generate_plan",
                    actionElapsedSeconds = 18,
                    actionProgress = 0.42f,
                    onGeneratePlan = {},
                    onRunStockSelection = {},
                    onStartRuntime = {},
                    onStopRuntime = {},
                    onGenerateReview = {},
                    onRefresh = {},
                )
            }
        }

        composeRule.onNodeWithText("正在执行 生成计划").assertIsDisplayed()
        composeRule.onNodeWithContentDescription("动作执行进度").assertIsDisplayed()
        composeRule.onNodeWithText("已耗时 18 秒，请在本页查看实时进度。").assertIsDisplayed()
        composeRule.onNodeWithContentDescription("刷新看板").assertIsNotEnabled()
    }

    @Test
    fun idleState_shouldEnableRefresh() {
        var refreshCount = 0
        composeRule.setContent {
            QuantSystemTheme {
                ActionsScreen(
                    isActionRunning = false,
                    runningAction = null,
                    actionElapsedSeconds = 0,
                    actionProgress = 0f,
                    onGeneratePlan = {},
                    onRunStockSelection = {},
                    onStartRuntime = {},
                    onStopRuntime = {},
                    onGenerateReview = {},
                    onRefresh = { refreshCount += 1 },
                )
            }
        }

        composeRule.onNodeWithContentDescription("刷新看板").assertIsEnabled().performClick()
        assertEquals(1, refreshCount)
    }

    @Test
    fun runSelection_shouldRequireConfirm_thenInvokeCallback() {
        var runSelectionCount = 0
        composeRule.setContent {
            QuantSystemTheme {
                ActionsScreen(
                    isActionRunning = false,
                    runningAction = null,
                    actionElapsedSeconds = 0,
                    actionProgress = 0f,
                    onGeneratePlan = {},
                    onRunStockSelection = { runSelectionCount += 1 },
                    onStartRuntime = {},
                    onStopRuntime = {},
                    onGenerateReview = {},
                    onRefresh = {},
                )
            }
        }

        composeRule.onNodeWithText("执行选股").performClick()
        composeRule.onNodeWithText("确认执行").assertIsDisplayed()
        composeRule.onNodeWithText("确认").performClick()

        assertEquals(1, runSelectionCount)
    }
}
