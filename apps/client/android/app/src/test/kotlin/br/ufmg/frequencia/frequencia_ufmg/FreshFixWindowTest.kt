package br.ufmg.frequencia.frequencia_ufmg
import org.junit.Assert.*
import org.junit.Test
class FreshFixWindowTest {
    @Test fun cachedThenPoorThenFreshKeepsWaitingUntilValid() {
        val gate = FreshFixWindow(1000000000)
        assertFalse(gate.offer(999000000, 1002000000, 20f))
        assertEquals("cached_fix_before_execution", gate.lastFailure)
        assertFalse(gate.offer(1003000000, 1004000000, 101f))
        assertEquals("inaccurate_fix", gate.lastFailure)
        assertTrue(gate.offer(1005000000, 1006000000, 25f))
        assertEquals(3, gate.sampleCount); assertEquals(2, gate.rejectedCount)
        assertNull(gate.lastFailure)
    }
    @Test fun cachedOnlyNeverBecomesAttendanceEvidence() {
        val gate = FreshFixWindow(500000000000)
        repeat(5) { assertFalse(gate.offer(499999000000, 500001000000, 10f)) }
        assertEquals(5, gate.sampleCount); assertEquals(5, gate.rejectedCount)
        assertEquals("cached_fix_before_execution", gate.lastFailure)
    }
}
