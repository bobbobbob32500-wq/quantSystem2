package com.quant.system

import android.os.Bundle
import android.view.animation.DecelerateInterpolator
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.quant.system.core.data.DataSyncOptimizer
import com.quant.system.core.stability.CrashReporter
import com.quant.system.core.stability.GlobalExceptionHandler
import com.quant.system.ui.screen.MainScreen
import com.quant.system.ui.theme.QuantSystemTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // 初始化全局异常处理器
        GlobalExceptionHandler.init(application)
        GlobalExceptionHandler.recordAppStart()
        
        // 记录会话开始
        CrashReporter.recordSessionStart(applicationContext)
        
        val splashScreen = installSplashScreen()
        super.onCreate(savedInstanceState)
        // 启动即注册后台同步：首轮尽快拉取，后续按周期维持刷新
        DataSyncOptimizer(applicationContext).apply {
            scheduleImmediateSync()
            schedulePeriodicSync(intervalMinutes = 15)
        }
        splashScreen.setOnExitAnimationListener { splashProvider ->
            splashProvider.view.animate()
                .alpha(0f)
                .setDuration(140L)
                .setInterpolator(DecelerateInterpolator())
                .withEndAction { splashProvider.remove() }
                .start()
        }
        setContent {
            QuantSystemTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainScreen()
                }
            }
        }
    }
    
    override fun onResume() {
        super.onResume()
        // 记录应用恢复
        GlobalExceptionHandler.logCriticalOperation("ActivityResume", true)
    }
    
    override fun onPause() {
        super.onPause()
        // 记录应用暂停
        GlobalExceptionHandler.logCriticalOperation("ActivityPause", true)
    }
    
    override fun onDestroy() {
        super.onDestroy()
        // 记录会话结束
        CrashReporter.recordSessionEnd(applicationContext, true)
    }
}
