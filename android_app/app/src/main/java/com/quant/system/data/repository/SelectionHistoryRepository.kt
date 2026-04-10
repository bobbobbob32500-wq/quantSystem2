package com.quant.system.data.repository

import android.content.Context
import com.quant.system.data.local.SelectionHistoryDbHelper
import com.quant.system.data.model.Candidate
import com.quant.system.data.model.StockSelectionHistoryRecord

class SelectionHistoryRepository(context: Context) {
    private val db = SelectionHistoryDbHelper(context)

    fun saveSelection(strategyKey: String, strategyLabel: String, candidates: List<Candidate>) {
        val key = strategyKey.trim().ifBlank { "unknown" }
        val label = strategyLabel.trim().ifBlank { key }
        db.insertSelection(key, label, candidates)
    }

    fun getRecentSelections(limit: Int = 20, strategyKey: String? = null): List<StockSelectionHistoryRecord> {
        return db.loadRecent(limit, strategyKey)
    }

    fun getLatestWithCandidates(): StockSelectionHistoryRecord? {
        return db.latestWithCandidates()
    }

    fun deleteSelection(id: Long): Boolean {
        return db.deleteById(id)
    }

    fun clearAll(): Int {
        return db.clearAll()
    }
}
