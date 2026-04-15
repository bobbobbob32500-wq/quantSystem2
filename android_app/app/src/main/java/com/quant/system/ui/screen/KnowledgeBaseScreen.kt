package com.quant.system.ui.screen

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quant.system.data.model.KnowledgeTopic
import com.quant.system.data.model.KnowledgeArticle

@Composable
fun KnowledgeBaseScreen(
    topics: List<KnowledgeTopic>,
    categories: List<String>,
    selectedArticle: KnowledgeArticle?,
    onQueryTopic: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var selectedCategory by remember { mutableStateOf<String?>(null) }
    var searchQuery by remember { mutableStateOf("") }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader(title = "量化知识库", subtitle = "技术指标、交易策略、风控方法")
        }

        // 搜索框
        item {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { searchQuery = it },
                label = { Text("搜索知识...") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
        }

        // 搜索按钮
        if (searchQuery.isNotBlank()) {
            item {
                PrimaryButton(
                    text = "搜索: $searchQuery",
                    onClick = { onQueryTopic(searchQuery) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        // 文章详情
        if (selectedArticle != null) {
            item {
                Card {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(selectedArticle.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        if (selectedArticle.category.isNotBlank()) {
                            Text(selectedArticle.category, fontSize = 12.sp, color = Color(0xFF6366F1))
                        }
                        HorizontalDivider()
                        Text(selectedArticle.content, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }

        // 分类筛选
        if (categories.isNotEmpty()) {
            item {
                Text("分类", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    FilterChip(
                        selected = selectedCategory == null,
                        onClick = { selectedCategory = null },
                        label = { Text("全部") },
                    )
                    categories.forEach { category ->
                        FilterChip(
                            selected = selectedCategory == category,
                            onClick = { selectedCategory = category },
                            label = { Text(category) },
                        )
                    }
                }
            }
        }

        // 主题列表
        val filteredTopics = if (selectedCategory != null) {
            topics.filter { it.category == selectedCategory }
        } else {
            topics
        }

        if (filteredTopics.isNotEmpty()) {
            items(filteredTopics, key = { it.key }) { topic ->
                KnowledgeTopicItem(topic, onClick = { onQueryTopic(topic.key) })
            }
        } else if (selectedArticle == null) {
            item {
                EmptyStateCard("暂无知识内容")
            }
        }

        item {
            SecondaryButton(text = "刷新", onClick = onRefresh, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun KnowledgeTopicItem(topic: KnowledgeTopic, onClick: () -> Unit) {
    Card(onClick = onClick) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(topic.title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                Text(topic.category, fontSize = 12.sp, color = Color.Gray)
            }
            Text("→", fontSize = 18.sp, color = Color.Gray)
        }
    }
}
