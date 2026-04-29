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
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import com.quant.system.ui.theme.Border
import com.quant.system.ui.theme.Primary
import com.quant.system.ui.theme.Surface
import com.quant.system.ui.theme.SurfaceVariant
import com.quant.system.ui.theme.TextPrimary
import com.quant.system.ui.theme.TextSecondary

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
    inferenceMode: String,
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
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        TopBar(
            title = "AI 管家",
            subtitle = "把候选、信号和持仓上下文交给 AI，总结判断、风险和后续动作。",
            eyebrow = "AI Butler",
        )

        HeroSection(
            title = "AI 工作台",
            value = if (aiAvailable) "在线" else "离线",
            subtitle = when (inferenceMode.lowercase()) {
                "cloud" -> "云端优先"
                "local" -> "本地优先"
                else -> "自动推理"
            },
            stats = listOf(
                Triple("会话", messages.size.toString(), ""),
                Triple("预警", (butlerStatus?.activeAlertsCount ?: 0).toString(), ""),
                Triple("管家", if (butlerStatus?.running == true) "运行中" else "空闲", ""),
            ),
        )

        AIStatusPanel(
            aiAvailable = aiAvailable,
            aiStatus = aiStatus,
            inferenceMode = inferenceMode,
            butlerStatus = butlerStatus,
            onStartButler = onStartButler,
            onStopButler = onStopButler,
            onClearHistory = onClearHistory,
        )

        ButlerAlertsPanel(alerts = butlerStatus?.activeAlerts.orEmpty())

        AIQuickActionsCard(
            enabled = aiAvailable,
            onQuickAsk = onQuickAsk,
        )

        Card(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = Surface),
            shape = RoundedCornerShape(24.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = "对话记录",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                )
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
                                text = "你好，我是 AI 管家。\n\n我可以结合当前候选池、信号和持仓，帮你解释为什么触发、哪里该谨慎、下一步该先看什么。",
                                style = MaterialTheme.typography.bodyLarge,
                                color = TextSecondary,
                                textAlign = TextAlign.Center,
                            )
                        }
                    } else {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxSize(),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            items(messages) { message ->
                                ChatMessageBubble(message)
                            }
                        }
                    }
                }
            }
        }

        Text(
            text = "提示：模型输出仅供辅助判断，不构成投资建议；实盘请继续以风控和策略纪律为准。",
            style = MaterialTheme.typography.labelSmall,
            color = TextSecondary,
        )

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
private fun AIStatusPanel(
    aiAvailable: Boolean,
    aiStatus: AIStatus?,
    inferenceMode: String,
    butlerStatus: ButlerStatus?,
    onStartButler: () -> Unit,
    onStopButler: () -> Unit,
    onClearHistory: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = if (aiAvailable) "AI 服务在线" else "AI 服务离线",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = aiStatus?.llmStatus?.defaultModel?.takeIf { it.isNotBlank() }?.let { "模型：$it" } ?: "模型信息暂不可用",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                    )
                }
                StatusPill(
                    text = if (butlerStatus?.running == true) "管家运行中" else "管家空闲",
                    tone = if (butlerStatus?.running == true) PillTone.Positive else PillTone.Neutral,
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                AIPanelMetric(
                    label = "推理",
                    value = when (inferenceMode.lowercase()) {
                        "cloud" -> "云端优先"
                        "local" -> "本地优先"
                        else -> "自动"
                    },
                    modifier = Modifier.weight(1f),
                )
                AIPanelMetric(
                    label = "最近简报",
                    value = butlerStatus?.lastBriefingTime ?: "--",
                    modifier = Modifier.weight(1f),
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PrimaryButton(
                    text = if (butlerStatus?.running == true) "停止管家" else "启动管家",
                    onClick = if (butlerStatus?.running == true) onStopButler else onStartButler,
                    modifier = Modifier.weight(1f),
                )
                SecondaryButton(
                    text = "清空对话",
                    onClick = onClearHistory,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun ButlerAlertsPanel(alerts: List<ButlerAlert>) {
    if (alerts.isEmpty()) return
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
        shape = RoundedCornerShape(22.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "管家预警",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.SemiBold,
            )
            alerts.take(6).forEach { alert ->
                Text(
                    text = "[${alert.level}] ${alert.type}：${alert.message}",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
            if (alerts.size > 6) {
                Text(
                    text = "其余 ${alerts.size - 6} 条已折叠。",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary,
                )
            }
        }
    }
}

@Composable
private fun AIQuickActionsCard(
    enabled: Boolean,
    onQuickAsk: (String) -> Unit,
) {
    val quickActions = listOf("市场分析", "选股逻辑", "风控策略", "策略优化")
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border.copy(alpha = 0.72f)),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "快捷提问",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.SemiBold,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                quickActions.forEach { action ->
                    SecondaryButton(
                        text = action,
                        onClick = { onQuickAsk(action) },
                        modifier = Modifier.weight(1f),
                        enabled = enabled,
                    )
                }
            }
        }
    }
}

@Composable
private fun AIPanelMetric(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = SurfaceVariant.copy(alpha = 0.58f)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(text = label, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
            Text(text = value, style = MaterialTheme.typography.titleSmall, color = TextPrimary, fontWeight = FontWeight.Bold)
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
                .fillMaxWidth(if (isSystem) 1f else 0.86f)
                .background(
                    when {
                        isUser -> Primary
                        isSystem -> Color(0xFFE9EFF6)
                        else -> SurfaceVariant
                    },
                    RoundedCornerShape(18.dp),
                )
                .padding(14.dp),
        ) {
            Text(
                text = if (message.isLoading) "思考中…" else message.content,
                color = if (isUser) Color.White else TextPrimary,
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
            placeholder = { Text(if (enabled) "输入问题…" else "请先确保 AI 可用") },
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
            shape = RoundedCornerShape(18.dp),
        )

        Column(
            verticalArrangement = Arrangement.spacedBy(4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                    }
                },
                enabled = enabled && inputText.isNotBlank(),
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
            }

            TextButton(onClick = onClear) {
                Text("清空", fontSize = 11.sp)
            }
        }
    }
}
