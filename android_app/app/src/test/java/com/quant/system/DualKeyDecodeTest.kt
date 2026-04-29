package com.quant.system

import kotlinx.serialization.SerialName
import kotlinx.serialization.SerializationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertTrue
import org.junit.Test

class DualKeyDecodeTest {

    @Serializable
    private data class Probe(
        @SerialName("candidate_pool")
        val candidatePool: Int? = null,
    )

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }

    @Test
    fun decode_with_primary_and_alternative_name_should_fail_or_resolve_consistently() {
        val payload = """{"candidate_pool":1,"candidatePool":2}"""
        val result = runCatching { json.decodeFromString<Probe>(payload) }
        if (result.isSuccess) {
            val value = result.getOrThrow().candidatePool
            assertTrue(value == 1 || value == 2)
        } else {
            val ex = result.exceptionOrNull()
            assertTrue(ex is SerializationException || ex is IllegalArgumentException)
        }
    }
}
