package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.EventChannel

/** A local notification of confirmed writes, not a polling loop or a network subscription. */
class CheckpointDeliveryEvents(context: Context) : EventChannel.StreamHandler {
    private val prefs = context.getSharedPreferences(FirstCheckpointBridge.INDEX, 0)
    private val handler = Handler(Looper.getMainLooper())
    private var sink: EventChannel.EventSink? = null
    private var listener: SharedPreferences.OnSharedPreferenceChangeListener? = null
    override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
        dispose()
        sink = events
        listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == REVISION || key == OPEN_REVISION || key == null) send()
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        send()
    }
    private fun send() { handler.post {
        val target=sink ?: return@post
        if(prefs.getBoolean("notice_open_pending",false)) {
            target.success(mapOf("action" to "open_checkpoints", "account_id" to prefs.getString("account_id",null), "open_revision" to prefs.getLong(OPEN_REVISION,0)))
            prefs.edit().putBoolean("notice_open_pending",false).apply()
        }
        target.success(mapOf("account_id" to prefs.getString("account_id", null), "revision" to prefs.getLong(REVISION, 0)))
    } }
    override fun onCancel(arguments: Any?) { dispose() }
    fun dispose() {
        listener?.let { prefs.unregisterOnSharedPreferenceChangeListener(it) }
        listener = null; sink = null
        handler.removeCallbacksAndMessages(null)
    }
    companion object {
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/checkpoint_delivery_events"
        const val OPEN_REVISION="notice_open_revision"
        const val REVISION = "delivery_revision"
    }
}
