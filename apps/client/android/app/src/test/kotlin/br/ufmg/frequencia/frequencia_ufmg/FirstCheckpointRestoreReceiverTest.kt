package br.ufmg.frequencia.frequencia_ufmg

import android.app.AlarmManager
import android.content.Intent
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstCheckpointRestoreReceiverTest {
    @Test
    fun `restores on direct boot and regular boot, update, clock, timezone and permission changes`() {
        val handled = listOf(
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            Intent.ACTION_TIME_CHANGED,
            Intent.ACTION_TIMEZONE_CHANGED,
            AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED,
        )
        handled.forEach { assertTrue("expected handled: $it", FirstCheckpointRestoreReceiver.handles(it)) }
    }

    @Test
    fun `ignores unrelated broadcasts`() {
        assertFalse(FirstCheckpointRestoreReceiver.handles(Intent.ACTION_BATTERY_CHANGED))
        assertFalse(FirstCheckpointRestoreReceiver.handles(null))
    }
}
