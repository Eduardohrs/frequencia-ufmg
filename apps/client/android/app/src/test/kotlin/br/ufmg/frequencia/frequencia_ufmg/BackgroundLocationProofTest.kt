package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.*
import org.junit.Test

class BackgroundLocationProofTest {
    @Test fun `permission flags alone never prove background location`() {
        assertEquals("permission_denied", BackgroundProofPolicy.blocked(false, true, true))
        assertEquals("background_permission_required", BackgroundProofPolicy.blocked(true, false, true))
        assertEquals("location_disabled", BackgroundProofPolicy.blocked(true, true, false))
        assertNull(BackgroundProofPolicy.blocked(true, true, true))
    }
    @Test fun `stale inaccurate and future fixes are not proof`() {
        assertEquals("stale_fix", BackgroundProofPolicy.fix(120001, 5f, true))
        assertEquals("future_fix", BackgroundProofPolicy.fix(-1, 5f, true))
        assertEquals("inaccurate_fix", BackgroundProofPolicy.fix(0, 101f, true))
        assertEquals("invalid_accuracy", BackgroundProofPolicy.fix(0, Float.NaN, true))
        assertEquals("invalid_accuracy", BackgroundProofPolicy.fix(0, -1f, true))
        assertNull(BackgroundProofPolicy.fix(120000, 100f, true))
        assertEquals("cached_fix_before_execution", BackgroundProofPolicy.fix(100, 1f, false))
    }
    @Test fun `a successful fix must also have been captured outside foreground`() {
        assertFalse(BackgroundProofPolicy.proven("succeeded", false, false))
        assertTrue(BackgroundProofPolicy.proven("succeeded", true, true))
        assertFalse(BackgroundProofPolicy.proven("succeeded", false, true))
        assertFalse(BackgroundProofPolicy.proven("succeeded", true, false))
        assertFalse(BackgroundProofPolicy.proven("location_timeout", true, true))
    }
    @Test fun `screen off battery saver never selects disabled GPS`() {
        assertEquals(listOf("network"), BackgroundProofPolicy.providers(true, true, 1, false, false))
        assertEquals(listOf("gps", "network"), BackgroundProofPolicy.providers(true, true, 1, true, false))
        assertEquals(emptyList<String>(), BackgroundProofPolicy.providers(true, true, 2, false, false))
        assertEquals(emptyList<String>(), BackgroundProofPolicy.providers(true, true, 3, true, false))
        assertEquals(listOf("gps"), BackgroundProofPolicy.providers(true, false, 3, true, true))
        assertEquals(listOf("network"), BackgroundProofPolicy.providers(false, true, 0, false, false))
        assertEquals(emptyList<String>(), BackgroundProofPolicy.providers(false, false, 0, false, false))
        assertEquals(listOf("gps"), BackgroundProofPolicy.providers(true, false, 4, false, false))
    }
    @Test fun `only a matching exited worker can turn running into interrupted`() {
        assertTrue(BackgroundProofPolicy.interrupted("running", 20, 30, 110, 100))
        assertFalse(BackgroundProofPolicy.interrupted("succeeded", 20, 30, 110, 100))
        assertFalse(BackgroundProofPolicy.interrupted("running", 0, 30, 110, 100))
        assertFalse(BackgroundProofPolicy.interrupted("running", 20, 20, 110, 100))
        assertFalse(BackgroundProofPolicy.interrupted("running", 20, 30, 90, 100))
    }
}
