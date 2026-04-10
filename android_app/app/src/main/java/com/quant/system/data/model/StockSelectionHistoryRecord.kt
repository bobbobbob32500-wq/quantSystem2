package com.quant.system.data.model

data class StockSelectionHistoryRecord(
    val id: Long,
    val strategyKey: String,
    val strategyLabel: String,
    val candidateCount: Int,
    val createdAtMillis: Long,
    val createdAtLabel: String,
    val topSymbols: List<String>,
    val candidates: List<Candidate>,
)
