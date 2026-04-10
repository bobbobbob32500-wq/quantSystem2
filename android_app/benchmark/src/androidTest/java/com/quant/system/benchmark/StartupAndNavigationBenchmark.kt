package com.quant.system.benchmark

import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.FrameTimingMetric
import androidx.benchmark.macro.MacrobenchmarkRule
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.junit4.BaselineProfileRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StartupAndNavigationBenchmark {

    @get:Rule
    val benchmarkRule = MacrobenchmarkRule()

    @get:Rule
    val baselineProfileRule = BaselineProfileRule()

    private val packageName = "com.quant.system"

    @Test
    fun startupCold() {
        benchmarkRule.measureRepeated(
            packageName = packageName,
            metrics = listOf(StartupTimingMetric()),
            iterations = 5,
            startupMode = StartupMode.COLD,
            compilationMode = CompilationMode.Partial(),
        ) {
            pressHome()
            startActivityAndWait()
        }
    }

    @Test
    fun tabNavigationFrameTiming() {
        benchmarkRule.measureRepeated(
            packageName = packageName,
            metrics = listOf(FrameTimingMetric()),
            iterations = 5,
            startupMode = StartupMode.WARM,
            compilationMode = CompilationMode.Partial(),
        ) {
            startActivityAndWait()
            val device = UiDevice.getInstance(instrumentation)
            device.wait(Until.hasObject(By.text("总览")), 5_000)
            device.findObject(By.text("候选池"))?.click()
            device.findObject(By.text("信号"))?.click()
            device.findObject(By.text("持仓"))?.click()
            device.findObject(By.text("总览"))?.click()
        }
    }

    @Test
    fun generateBaselineProfile() {
        baselineProfileRule.collect(
            packageName = packageName,
            maxIterations = 3,
        ) {
            startActivityAndWait()
            val device = UiDevice.getInstance(instrumentation)
            device.wait(Until.hasObject(By.text("总览")), 5_000)
            device.findObject(By.text("候选池"))?.click()
            device.findObject(By.text("信号"))?.click()
            device.findObject(By.text("持仓"))?.click()
            device.findObject(By.text("总览"))?.click()
        }
    }
}
