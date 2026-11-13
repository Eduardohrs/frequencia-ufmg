package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.assertEquals
import org.junit.Test

class FirstCheckpointBootIndexTest {
    @Test
    fun `boot index round-trips key to expected timestamp`() {
        val entries = mapOf("first_checkpoint_a" to 1_700_000_000_000L, "first_checkpoint_b" to 1_700_000_060_000L)
        val decoded = FirstCheckpointBootIndex.decode(FirstCheckpointBootIndex.encode(entries))
        assertEquals(entries, decoded)
    }

    @Test
    fun `boot index decodes empty and corrupt payloads as empty`() {
        assertEquals(emptyMap<String, Long>(), FirstCheckpointBootIndex.decode(null))
        assertEquals(emptyMap<String, Long>(), FirstCheckpointBootIndex.decode(""))
        assertEquals(emptyMap<String, Long>(), FirstCheckpointBootIndex.decode("{}"))
    }
}
