package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

class MaterialDownloadExecutionTest {
    @Test
    fun `a new attempt supersedes historical failure rows for the same file`() {
        val attempts = listOf(
            "old failure" to setOf("legacy-item-tag"),
            "new completed" to setOf("item-tag", "material-queued-at-200"),
            "previous failure" to setOf("item-tag", "material-queued-at-100"),
        )
        assertEquals("new completed", attempts.sortedByDescending {
            MaterialDownloadExecution.queuedAt(it.second)
        }.first().first)
        assertEquals(0L, MaterialDownloadExecution.queuedAt(setOf("material-queued-at-invalid")))
    }

    @Test
    fun `modern background downloads never invoke the forbidden foreground service`() {
        for (sdk in listOf(31, 32, 33, 34, 35, 36)) {
            var notifications = 0
            MaterialDownloadExecution.updateNotification(
                sdk,
                notify = { notifications++ },
                startForeground = { error("Android rejects this when the app is backgrounded") },
                notificationDenied = { throw it },
            )
            assertEquals(1, notifications)
        }
    }

    @Test
    fun `notification denial is observable without failing scheduled execution`() {
        val denial = SecurityException("POST_NOTIFICATIONS denied")
        var reported: Throwable? = null
        MaterialDownloadExecution.updateNotification(
            36,
            notify = { throw denial },
            startForeground = { error("Must not fall back to a forbidden service") },
            notificationDenied = { reported = it },
        )
        assertSame(denial, reported)
    }

    @Test
    fun `legacy versions retain foreground execution and propagate actual startup failures`() {
        for (sdk in listOf(24, 29, 30)) {
            var foregroundStarts = 0
            MaterialDownloadExecution.updateNotification(
                sdk,
                notify = { error("Legacy foreground notification is owned by WorkManager") },
                startForeground = { foregroundStarts++ },
                notificationDenied = { throw it },
            )
            assertEquals(1, foregroundStarts)
        }
        val failure = IllegalStateException("service failure")
        assertSame(failure, assertThrows(IllegalStateException::class.java) {
            MaterialDownloadExecution.updateNotification(
                30, notify = {}, startForeground = { throw failure }, notificationDenied = {},
            )
        })
    }
}
