package com.quant.system.data.api

import org.junit.Assert.assertEquals
import org.junit.Test

class RetrofitClientTest {

    @Test
    fun `normalizeBaseUrl should append slash when missing`() {
        val normalized = RetrofitClient.normalizeBaseUrl("http://127.0.0.1:8000")
        assertEquals("http://127.0.0.1:8000/", normalized)
    }

    @Test
    fun `normalizeBaseUrl should keep slash when already exists`() {
        val normalized = RetrofitClient.normalizeBaseUrl("http://127.0.0.1:8000/")
        assertEquals("http://127.0.0.1:8000/", normalized)
    }

    @Test
    fun `normalizeBaseUrl should trim whitespace`() {
        val normalized = RetrofitClient.normalizeBaseUrl("  http://10.0.2.2:8000/api  ")
        assertEquals("http://10.0.2.2:8000/api/", normalized)
    }
}
