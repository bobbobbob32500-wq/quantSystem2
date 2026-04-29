package com.quant.system

import com.quant.system.data.model.ApiResponse
import com.quant.system.data.model.DashboardSnapshot
import java.nio.file.Files
import java.nio.file.Path
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OverviewContractDecodeTest {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }

    @Test
    fun decode_overview_payload_should_keep_non_zero_counts() {
        val payload = readOverviewPayload()
        val parsed = json.decodeFromString<ApiResponse<DashboardSnapshot>>(payload)
        val snapshot = parsed.data

        assertNotNull("overview.data should not be null", snapshot)
        val candidateCount = snapshot?.candidatePool?.count ?: snapshot?.candidatePool?.topCandidates?.size ?: 0
        val signalCount = snapshot?.signals?.recentCount ?: snapshot?.signals?.latestItems?.size ?: 0
        val openCount = snapshot?.virtualTrades?.openCount ?: snapshot?.virtualTrades?.openTrades?.size ?: 0

        assertTrue("candidate count should be > 0 after decode", candidateCount > 0)
        assertTrue("signal count should be > 0 after decode", signalCount > 0)
        assertTrue("open trade count should be > 0 after decode", openCount > 0)
    }

    private fun readOverviewPayload(): String {
        val candidates = listOf(
            Path.of("..", "..", "phone_overview_now.json"),
            Path.of("..", "..", "tmp_overview.json"),
            Path.of("..", "..", "phone_overview.json"),
            Path.of("..", "phone_overview_now.json"),
            Path.of("..", "tmp_overview.json"),
        )
        val existing = candidates.firstOrNull { Files.exists(it) }
            ?: error("No overview payload fixture found in project root")
        return String(Files.readAllBytes(existing), Charsets.UTF_8)
    }
}
