package com.quant.system.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.quant.system.ui.screen.viewmodel.NoticeType

private enum class LogFilter(val label: String) {
    All("全部"),
    Signal("信号"),
    Action("动作"),
    Test("测试"),
}

@Composable
fun NotificationLogsScreen(
    logs: List<String>,
    message: String?,
    noticeType: NoticeType,
    onClear: () -> Unit,
    onExport: (String) -> Unit,
    onRefreshHint: () -> Unit,
) {
    var filter by remember { mutableStateOf(LogFilter.All) }
    val filteredLogs = remember(logs, filter) {
        logs.map { it.substringAfter("|", it) }.filter { line ->
            when (filter) {
                LogFilter.All -> true
                LogFilter.Signal -> "[SIGNAL]" in line
                LogFilter.Action -> "[ACTION]" in line
                LogFilter.Test -> "[TEST]" in line
            }
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(
                title = "通知触发日志",
                subtitle = "查看通知是发送还是被过滤，便于真机联调排查",
            )
        }
        if (!message.isNullOrBlank()) {
            item { NoticeBanner(message = message, type = noticeType, onRetry = onRefreshHint) }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                LogFilter.entries.forEach { option ->
                    SecondaryButton(
                        text = option.label,
                        onClick = { filter = option },
                        modifier = Modifier.weight(1f),
                        enabled = filter != option,
                    )
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onClear, modifier = Modifier.weight(1f)) {
                    Text("清空日志")
                }
                OutlinedButton(
                    onClick = {
                        val exportText = filteredLogs.take(100).joinToString(separator = "\n")
                        onExport(exportText.ifBlank { "暂无日志可导出" })
                    },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("导出前100条")
                }
            }
        }
        if (filteredLogs.isEmpty()) {
            item { EmptyStateCard("暂无通知日志，触发一次测试通知后再查看") }
        } else {
            items(filteredLogs, key = { it }) { line ->
                DetailCard(title = "日志记录", lines = listOf(line))
            }
        }
    }
}
