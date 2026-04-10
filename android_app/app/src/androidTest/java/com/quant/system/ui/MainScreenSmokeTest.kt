package com.quant.system.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.quant.system.MainActivity
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainScreenSmokeTest {

    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun bottomTabs_shouldBeVisible() {
        composeRule.onNodeWithText("总览").assertIsDisplayed()
        composeRule.onNodeWithText("候选池").assertIsDisplayed()
        composeRule.onNodeWithText("信号").assertIsDisplayed()
        composeRule.onNodeWithText("持仓").assertIsDisplayed()
    }

    @Test
    fun navigation_shouldSwitchBetweenTabs() {
        composeRule.onNodeWithText("候选池").performClick()
        composeRule.onNodeWithText("执行选股").assertIsDisplayed()

        composeRule.onNodeWithText("信号").performClick()
        composeRule.onNodeWithText("最近信号").assertIsDisplayed()

        composeRule.onNodeWithText("持仓").performClick()
        composeRule.onNodeWithText("持仓管理").assertIsDisplayed()
    }
}
