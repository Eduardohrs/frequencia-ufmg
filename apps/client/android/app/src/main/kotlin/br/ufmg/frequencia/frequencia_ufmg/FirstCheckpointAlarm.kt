package br.ufmg.frequencia.frequencia_ufmg

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import org.json.JSONObject

/** Exact wakeup goes directly to the location foreground service, never through JobScheduler. */
class FirstCheckpointAlarm(private val context: Context) {
    private val alarms get() = context.getSystemService(AlarmManager::class.java)
    fun allowed(): Boolean = Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()
    private fun operation(key: String, flags: Int): PendingIntent? {
        val intent = Intent(context, FirstCheckpointService::class.java)
            .setAction("capture_first_checkpoint").setData(Uri.parse("frequencia://first-checkpoint/$key"))
        val immutable = flags or PendingIntent.FLAG_IMMUTABLE
        return if (Build.VERSION.SDK_INT >= 26) PendingIntent.getForegroundService(context, 0, intent, immutable)
            else PendingIntent.getService(context, 0, intent, immutable)
    }
    fun schedule(key: String, expected: Long) {
        check(allowed()) { "exact_alarm_permission_required" }
        alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, expected,
            operation(key, PendingIntent.FLAG_UPDATE_CURRENT)!!)
    }
    fun cancel(key: String) {
        operation(key, PendingIntent.FLAG_NO_CREATE)?.let { alarms.cancel(it); it.cancel() }
        FirstCheckpointService.cancel(key)
    }
}

/** Rebuild alarms from the local account-scoped index after reboot, update, or clock changes. */
class FirstCheckpointRestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED,
                Intent.ACTION_TIME_CHANGED, AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED)) return
        val pending = goAsync()
        Thread {
            try { FirstCheckpointBridge(context).restore(intent.action ?: "unknown") }
            catch (error: Exception) {
                BackgroundLocationProof.emit(JSONObject().put("event_stage", "alarm_restore")
                    .put("moment", "first").put("status", "alarm_restore_failed")
                    .put("trigger", intent.action).put("cause_type", error.javaClass.simpleName)
                    .put("cause_message", error.message?.take(300)))
            } finally { pending.finish() }
        }.start()
    }
}
