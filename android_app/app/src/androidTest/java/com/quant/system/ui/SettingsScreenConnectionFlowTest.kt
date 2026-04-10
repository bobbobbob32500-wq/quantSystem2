package com.quant.system.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import com.quant.system.ui.screen.SettingsScreen
import com.quant.system.ui.screen.viewmodel.DebugPanelState
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.QuantSystemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SettingsScreenConnectionFlowTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun apiInput_shouldInvokeOnBaseUrlChange() {
        var capturedBaseUrl = ""
        composeRule.setContent {
            QuantSystemTheme {
                SettingsScreen(
                    currentBaseUrl = "https://old.ngrok-free.dev/",
                    baseUrlInput = "https://old.ngrok-free.dev/",
                    message = null,
                    noticeType = NoticeType.Info,
                    isSaving = false,
                    currentVersionName = "1.0.4",
                    currentVersionCode = 104,
                    isCheckingUpdate = false,
                    latestUpdate = null,
                    highContrastEnabled = false,
                    defaultStrategy = "secondary_launch",
                    homeModuleOrder = "overview,task,health,metrics,signals",
                    watchlistSymbols = emptyList(),
                    isNotificationPermissionGranted = false,
                    notifyHighPrioritySignalOnly = false,
                    notifyActionCompleteEnabled = true,
                    silentStart = "22:30",
                    silentEnd = "07:30",
                    signalPriorityKeywords = "buy,strong",
                    notificationLogRetentionDays = 7,
                    notificationLogsCount = 0,
                    debugPanel = DebugPanelState(),
                    onBaseUrlChange = { capturedBaseUrl = it },
                    onToggleHighContrast = {},
                    onSave = {},
                    onTestConnection = {},
                    onCheckUpdate = {},
                    onInstallUpdate = {},
                    onRequestNotificationPermission = {},
                    onSendTestNotification = {},
                    showOpenNotificationSettings = false,
                    onOpenNotificationSettings = {},
                    onSaveDefaultStrategy = {},
                    onSaveHomeModuleOrder = {},
                    onSaveWatchlist = {},
                    onSetHighPrioritySignalOnly = {},
                    onSetActionCompleteNotifyEnabled = {},
                    onSaveSilentWindow = { _, _ -> },
                    onSaveSignalPriorityKeywords = {},
                    onSaveNotificationLogRetentionDays = {},
                    onOpenNotificationLogs = {},
                    onCopyBaseUrl = {},
                    onCopyDocsUrl = {},
                    onOpenDocs = {},
                )
            }
        }

        val nextUrl = "https://silvicultural-nonrectangularly-lyle.ngrok-free.dev/"
        composeRule.onNodeWithContentDescription("API 地址输入框").assertIsDisplayed()
        composeRule.onNodeWithContentDescription("API 地址输入框").performTextClearance()
        composeRule.onNodeWithContentDescription("API 地址输入框").performTextInput(nextUrl)

        assertEquals(nextUrl, capturedBaseUrl)
    }

    @Test
    fun connectionButtons_shouldInvokeCallbacks() {
        var testConnectionCount = 0
        var saveCount = 0
        composeRule.setContent {
            QuantSystemTheme {
                SettingsScreen(
                    currentBaseUrl = "https://silvicultural-nonrectangularly-lyle.ngrok-free.dev/",
                    baseUrlInput = "https://silvicultural-nonrectangularly-lyle.ngrok-free.dev/",
                    message = "连接信息",
                    noticeType = NoticeType.Info,
                    isSaving = false,
                    currentVersionName = "1.0.4",
                    currentVersionCode = 104,
                    isCheckingUpdate = false,
                    latestUpdate = null,
                    highContrastEnabled = false,
                    defaultStrategy = "secondary_launch",
                    homeModuleOrder = "overview,task,health,metrics,signals",
                    watchlistSymbols = listOf("000001"),
                    isNotificationPermissionGranted = true,
                    notifyHighPrioritySignalOnly = false,
                    notifyActionCompleteEnabled = true,
                    silentStart = "22:30",
                    silentEnd = "07:30",
                    signalPriorityKeywords = "buy,strong",
                    notificationLogRetentionDays = 7,
                    notificationLogsCount = 3,
                    debugPanel = DebugPanelState(backendStatusLabel = "连接正常"),
                    onBaseUrlChange = {},
                    onToggleHighContrast = {},
                    onSave = { saveCount += 1 },
                    onTestConnection = { testConnectionCount += 1 },
                    onCheckUpdate = {},
                    onInstallUpdate = {},
                    onRequestNotificationPermission = {},
                    onSendTestNotification = {},
                    showOpenNotificationSettings = false,
                    onOpenNotificationSettings = {},
                    onSaveDefaultStrategy = {},
                    onSaveHomeModuleOrder = {},
                    onSaveWatchlist = {},
                    onSetHighPrioritySignalOnly = {},
                    onSetActionCompleteNotifyEnabled = {},
                    onSaveSilentWindow = { _, _ -> },
                    onSaveSignalPriorityKeywords = {},
                    onSaveNotificationLogRetentionDays = {},
                    onOpenNotificationLogs = {},
                    onCopyBaseUrl = {},
                    onCopyDocsUrl = {},
                    onOpenDocs = {},
                )
            }
        }

        composeRule.onNodeWithText("测试连接").assertIsDisplayed().performClick()
        composeRule.onNodeWithText("保存并使用该地址").assertIsDisplayed().performClick()

        assertEquals(1, testConnectionCount)
        assertEquals(1, saveCount)
    }
}
