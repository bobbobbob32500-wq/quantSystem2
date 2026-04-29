package com.quant.system.core.signal

import com.quant.system.data.model.SignalItem
import java.util.Locale

object SignalNotificationPolicy {
    private val buyKeywords = listOf(
        "buy", "long", "breakout",
        "买", "做多", "看多", "建仓", "加仓", "开仓", "突破",
    )
    private val sellKeywords = listOf(
        "sell", "short", "exit", "close",
        "卖", "减仓", "清仓", "止盈", "止损", "离场", "平仓",
    )

    fun signalKey(item: SignalItem): String? {
        val code = item.tsCode?.trim().orEmpty()
        if (code.isBlank()) return null
        return "$code|${item.signalTime.orEmpty()}|${item.signalType.orEmpty()}"
    }

    fun isBuySignal(item: SignalItem): Boolean {
        val text = listOf(item.signalType, item.triggerReason, item.suggestion)
            .joinToString(" ")
            .lowercase(Locale.getDefault())
        if (text.isBlank()) return false
        if (sellKeywords.any { text.contains(it) }) return false
        return buyKeywords.any { text.contains(it) }
    }

    fun buildTitle(item: SignalItem): String {
        return "买点信号 ${item.tsCode.orEmpty().ifBlank { "--" }}"
    }

    fun buildContent(item: SignalItem): String {
        val signal = item.signalType?.trim().orEmpty().ifBlank { "买点触发" }
        val reason = item.triggerReason?.trim().orEmpty().ifBlank { item.suggestion?.trim().orEmpty() }
        return if (reason.isBlank()) {
            signal
        } else {
            "$signal · ${reason.take(26)}"
        }
    }
}
