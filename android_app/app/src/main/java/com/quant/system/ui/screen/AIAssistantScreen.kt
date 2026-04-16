package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.AIStatus
import com.quant.system.data.model.ButlerAlert
import com.quant.system.data.model.ButlerStatus
import com.quant.system.data.model.ChatMessage

@Composable
fun AIAssistantScreen(
    aiAvailable: Boolean,
    aiStatus: AIStatus?,
    butlerStatus: ButlerStatus?,
    onSendMessage: (String) -> Unit,
    onQuickAsk: (String) -> Unit,
    onStartButler: () -> Unit,
    onStopButler: () -> Unit,
    messages: List<ChatMessage>,
    inputText: String,
    onInputTextChange: (String) -> Unit,
    onClearHistory: () -> Unit,
) {
    val listState = rememberLazyListState()

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.scrollToItem(messages.size - 1)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        AIStatusBar(
            aiAvailable = aiAvailable,
            aiStatus = aiStatus,
            butlerRunning = butlerStatus?.running ?: false,
            onStartButler = onStartButler,
            onStopButler = onStopButler,
        )

        Spacer(modifier = Modifier.height(10.dp))

        ButlerAlertsSection(alerts = butlerStatus?.activeAlerts.orEmpty())

        Spacer(modifier = Modifier.height(10.dp))

        QuickActionButtons(
            enabled = aiAvailable,
            onQuickAsk = onQuickAsk,
        )

        Spacer(modifier = Modifier.height(10.dp))

        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
        ) {
            if (messages.isEmpty()) {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "你好！我是 AI 管家，可结合你当前候选池与持仓做说明（摘要由本机随请求传给后端，不含账户密码）。\n\n请问有什么可以帮你的？",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(messages) { message ->
                        ChatMessageBubble(message)
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "提示：大模型输出仅供参考，不构成投资建议；实盘请严格风控并注意滑点与过拟合风险。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(modifier = Modifier.height(8.dp))

        ChatInputArea(
            inputText = inputText,
            onInputTextChange = onInputTextChange,
            onSend = onSendMessage,
            onClear = onClearHistory,
            enabled = aiAvailable,
        )
    }
}

@Composable
private fun AIStatusBar(
    aiAvailable: Boolean,
    aiStatus: AIStatus?,
    butlerRunning: Boolean,
    onStartButler: () -> Unit,
    onStopButler: () -> Unit,
) {
    val modelLine = aiStatus?.llmStatus?.defaultModel?.takeIf { it.isNotBlank() }?.let { "模型：$it" } ?: ""

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                if (aiAvailable) Color(0xFF22C55E).copy(alpha = 0.1f)
                else Color(0xFFEF4444).copy(alpha = 0.1f),
                RoundedCornerShape(8.dp),
            )
            .padding(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(
                            if (aiAvailable) Color(0xFF22C55E) else Color(0xFFEF4444),
                            RoundedCornerShape(4.dp),
                        ),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = if (aiAvailable) "AI服务在线" else "AI服务离线",
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (butlerRunning) {
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "| 管家运行中",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color(0xFF6366F1),
                    )
                }
            }
            Row {
                if (!butlerRunning) {
                    TextButton(onClick = onStartButler) {
                        Text("启动管家", fontSize = 12.sp)
                    }
                } else {
                    TextButton(onClick = onStopButler) {
                        Text("停止管家", fontSize = 12.sp)
                    }
                }
            }
        }
        if (modelLine.isNotBlank()) {
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = modelLine,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ButlerAlertsSection(alerts: List<ButlerAlert>) {
    if (alerts.isEmpty()) return
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.6f),
                RoundedCornerShape(8.dp),
            )
            .padding(10.dp),
    ) {
        Text(
            text = "管家预警（${alerts.size}）",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(modifier = Modifier.height(6.dp))
        alerts.take(6).forEach { a ->
            Text(
                text = "[${a.level}] ${a.type}：${a.message}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
            )
            Spacer(modifier = Modifier.height(4.dp))
        }
        if (alerts.size > 6) {
            Text(
                text = "… 其余 ${alerts.size - 6} 条已省略",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun QuickActionButtons(
    enabled: Boolean,
    onQuickAsk: (String) -> Unit,
) {
    val quickActions = listOf("市场分析", "选股逻辑", "风控策略", "策略优化")

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        quickActions.forEach { action ->
            OutlinedButton(
                onClick = { onQuickAsk(action) },
                modifier = Modifier.weight(1f),
                enabled = enabled,
                shape = RoundedCornerShape(20.dp),
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Text(action, fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun ChatMessageBubble(message: ChatMessage) {
    val isUser = message.role == "user"
    val isSystem = message.role == "system"

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(if (isSystem) 1f else 0.85f)
                .background(
                    when {
                        isUser -> MaterialTheme.colorScheme.primary
                        isSystem -> Color(0xFF6366F1).copy(alpha = 0.1f)
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    },
                    RoundedCornerShape(12.dp),
                )
                .padding(12.dp),
        ) {
            Text(
                text = if (message.isLoading) "思考中…" else message.content,
                color = if (isUser) Color.White else MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun ChatInputArea(
    inputText: String,
    onInputTextChange: (String) -> Unit,
    onSend: (String) -> Unit,
    onClear: () -> Unit,
    enabled: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = inputText,
            onValueChange = onInputTextChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text(if (enabled) "输入问题…" else "请先配置后端并确保 AI 可用") },
            enabled = enabled,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(
                onSend = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                    }
                },
            ),
            maxLines = 3,
            shape = RoundedCornerShape(12.dp),
        )

        Column(
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                    }
                },
                enabled = enabled && inputText.isNotBlank(),
            ) {
                Icon(Icons.Default.Send, contentDescription = "发送")
            }

            TextButton(
                onClick = onClear,
                modifier = Modifier.padding(0.dp),
            ) {
                Text("清空", fontSize = 11.sp)
            }
        }
    }
}
