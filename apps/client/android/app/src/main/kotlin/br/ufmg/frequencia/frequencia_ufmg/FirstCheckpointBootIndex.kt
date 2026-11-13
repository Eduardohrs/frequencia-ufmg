package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import android.os.Build
import android.os.UserManager
import org.json.JSONObject

/**
 * Minimal alarm index kept in device-protected storage so alarms can be rearmed
 * during Direct Boot (before the first unlock), when credential-protected
 * SharedPreferences are unavailable. Only key -> expected_at_ms is mirrored;
 * full reports stay in the regular account-scoped stores.
 */
object FirstCheckpointBootIndex {
    const val NAME = "first_checkpoint_boot_index"
    const val KEY_ENTRIES = "alarms"

    fun isDirectBoot(context: Context): Boolean =
        Build.VERSION.SDK_INT >= 24 &&
            !(context.getSystemService(UserManager::class.java)?.isUserUnlocked ?: true)

    fun deviceProtected(context: Context): Context =
        if (Build.VERSION.SDK_INT >= 24) context.createDeviceProtectedStorageContext() else context

    private fun prefs(context: Context) = deviceProtected(context).getSharedPreferences(NAME, 0)

    fun encode(entries: Map<String, Long>): String =
        JSONObject(entries.mapValues { it.value as Any }).toString()

    fun decode(raw: String?): Map<String, Long> {
        if (raw.isNullOrEmpty()) return emptyMap()
        val obj = JSONObject(raw)
        return obj.keys().asSequence().associateWith { obj.getLong(it) }
    }

    fun put(context: Context, key: String, expectedAtMs: Long) {
        val entries = decode(prefs(context).getString(KEY_ENTRIES, null)).toMutableMap()
        entries[key] = expectedAtMs
        prefs(context).edit().putString(KEY_ENTRIES, encode(entries)).commit()
    }

    fun remove(context: Context, key: String) {
        val entries = decode(prefs(context).getString(KEY_ENTRIES, null)).toMutableMap()
        if (entries.remove(key) != null) {
            prefs(context).edit().putString(KEY_ENTRIES, encode(entries)).commit()
        }
    }

    fun clear(context: Context) {
        prefs(context).edit().clear().commit()
    }

    /** Rearm exact alarms from the device-protected index; used on LOCKED_BOOT_COMPLETED. */
    fun restoreAlarms(context: Context, trigger: String): Int {
        val alarms = FirstCheckpointAlarm(deviceProtected(context))
        if (!alarms.allowed()) return 0
        var rearmed = 0
        for ((key, expected) in decode(prefs(context).getString(KEY_ENTRIES, null))) {
            try {
                alarms.schedule(key, expected)
                rearmed++
            } catch (_: Exception) {
                // Exact-alarm permission may be missing pre-unlock; BOOT_COMPLETED retries after unlock.
            }
        }
        if (rearmed > 0 || trigger.isNotEmpty()) {
            BackgroundLocationProof.emit(JSONObject()
                .put("event_stage", "alarm_restore")
                .put("moment", "boot_index")
                .put("status", "rearmed")
                .put("trigger", trigger)
                .put("rearmed", rearmed))
        }
        return rearmed
    }
}
