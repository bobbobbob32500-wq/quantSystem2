package com.quant.system.ui

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.quant.system.ui.screen.NoticeBanner
import com.quant.system.ui.screen.viewmodel.NoticeType
import com.quant.system.ui.theme.QuantSystemTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class NoticeBannerRetryTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun errorNotice_shouldShowRetry_andInvokeCallback() {
        var retryCount = 0
        composeRule.setContent {
            QuantSystemTheme {
                NoticeBanner(
                    message = "请求超时，请稍后重试",
                    type = NoticeType.Error,
                    onRetry = { retryCount += 1 },
                )
            }
        }

        composeRule.onNodeWithText("请求超时，请稍后重试").assertIsDisplayed()
        composeRule.onNodeWithText("重试").assertIsDisplayed().performClick()
        assertEquals(1, retryCount)
    }

    @Test
    fun infoNotice_shouldHideRetryButton() {
        composeRule.setContent {
            QuantSystemTheme {
                NoticeBanner(
                    message = "连接成功",
                    type = NoticeType.Info,
                    onRetry = {},
                )
            }
        }

        composeRule.onNodeWithText("连接成功").assertIsDisplayed()
        composeRule.onAllNodesWithText("重试").assertCountEquals(0)
    }

    @Test
    fun errorNotice_withoutRetryCallback_shouldHideRetryButton() {
        composeRule.setContent {
            QuantSystemTheme {
                NoticeBanner(
                    message = "服务器错误（500）",
                    type = NoticeType.Error,
                    onRetry = null,
                )
            }
        }

        composeRule.onNodeWithText("服务器错误（500）").assertIsDisplayed()
        composeRule.onAllNodesWithText("重试").assertCountEquals(0)
    }
}
