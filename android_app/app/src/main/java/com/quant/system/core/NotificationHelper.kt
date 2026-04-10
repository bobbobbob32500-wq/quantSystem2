package com.quant.system.core

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.quant.system.R
import java.util.concurrent.atomic.AtomicInteger

class NotificationHelper(private val context: Context) {
    private val idGenerator = AtomicInteger(1000)

    init {
        createChannels()
    }

    fun canPostNotifications(): Boolean = isNotificationAllowed()

    fun notifyActionResult(title: String, content: String) {
        post(
            channelId = CHANNEL_ACTIONS,
            title = title,
            content = content,
        )
    }

    fun notifySignalUpdate(title: String, content: String) {
        post(
            channelId = CHANNEL_SIGNALS,
            title = title,
            content = content,
        )
    }

    fun notifyTest() {
        post(
            channelId = CHANNEL_ACTIONS,
            title = "通知测试",
            content = "推送链路正常，可接收动作与信号提醒。",
        )
    }

    private fun post(channelId: String, title: String, content: String) {
        if (!isNotificationAllowed()) return
        val builder = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
        safeNotify(builder)
    }

    @SuppressLint("MissingPermission")
    private fun safeNotify(builder: NotificationCompat.Builder) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        runCatching {
            NotificationManagerCompat.from(context).notify(idGenerator.incrementAndGet(), builder.build())
        }
    }

    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val actionChannel = NotificationChannel(
            CHANNEL_ACTIONS,
            "动作结果通知",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "动作执行完成或超时提醒"
        }
        val signalChannel = NotificationChannel(
            CHANNEL_SIGNALS,
            "信号提醒",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "出现新交易信号时提醒"
        }
        manager.createNotificationChannel(actionChannel)
        manager.createNotificationChannel(signalChannel)
    }

    private fun isNotificationAllowed(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }
    }

    private companion object {
        const val CHANNEL_ACTIONS = "quant_actions"
        const val CHANNEL_SIGNALS = "quant_signals"
    }
}
