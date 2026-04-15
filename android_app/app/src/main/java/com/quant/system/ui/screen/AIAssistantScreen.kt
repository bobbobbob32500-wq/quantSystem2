package com.quant.system.ui.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.ButlerStatus

data class ChatMessage(
    val role: String, // "user", "assistant", "system"
    val content: String,
    val isLoading: Boolean = false,
)

@Composable
fun AIAssistantScreen(
    aiAvailable: Boolean,
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
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // 状态栏
        AIStatusBar(
            aiAvailable = aiAvailable,
            butlerRunning = butlerStatus?.running ?: false,
            onStartButler = onStartButler,
            onStopButler = onStopButler,
        )

        Spacer(modifier = Modifier.height(12.dp))

        // 快速操作按钮
        QuickActionButtons(onQuickAsk = onQuickAsk)

        Spacer(modifier = Modifier.height(12.dp))

        // 消息列表
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        ) {
            if (messages.isEmpty()) {
                // 欢迎消息
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "你好！我是AI管家，可以帮你分析选股、解读信号、监控风险。\n\n请问有什么可以帮你的？",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(messages) { message ->
                        ChatMessageBubble(message)
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // 输入区域
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
    butlerRunning: Boolean,
    onStartButler: () -> Unit,
    onStopButler: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                if (aiAvailable) Color(0xFF22C55E).copy(alpha = 0.1f)
                else Color(0xFFEF4444).copy(alpha = 0.1f),
                RoundedCornerShape(8.dp)
            )
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(
                        if (aiAvailable) Color(0xFF22C55E) else Color(0xFFEF4444),
                        RoundedCornerShape(4.dp)
                    )
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = if (aiAvailable) "AI服务在线" else "AI服务离线",
                style = MaterialTheme.typography.bodyMedium
            )
            if (butlerRunning) {
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "| 管家运行中",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color(0xFF6366F1)
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
}

@Composable
private fun QuickActionButtons(
    onQuickAsk: (String) -> Unit,
) {
    val quickActions = listOf("市场分析", "选股逻辑", "风控策略", "策略优化")

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        quickActions.forEach { action ->
            OutlinedButton(
                onClick = { onQuickAsk(action) },
                modifier = Modifier.weight(1f),
                shape = RoundedCornerShape(20.dp),
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp)
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
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
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
                    RoundedCornerShape(12.dp)
                )
                .padding(12.dp)
        ) {
            Text(
                text = if (message.isLoading) "思考中..." else message.content,
                color = if (isUser) Color.White else MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium
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
        verticalAlignment = Alignment.CenterVertically
    ) {
        OutlinedTextField(
            value = inputText,
            onValueChange = onInputTextChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("输入问题...") },
            enabled = enabled,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = {
                if (inputText.isNotBlank()) {
                    onSend(inputText)
                }
            }),
            maxLines = 3,
            shape = RoundedCornerShape(12.dp),
        )

        Column(
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                    }
                },
                enabled = enabled && inputText.isNotBlank()
            ) {
                Icon(Icons.Default.Send, contentDescription = "发送")
            }

            TextButton(
                onClick = onClear,
                modifier = Modifier.padding(0.dp)
            ) {
                Text("清空", fontSize = 11.sp)
            }
        }
    }
}
