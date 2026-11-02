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
            if (key == REVISION || key == null) send()
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        send()
    }
    private fun send() { handler.post {
        sink?.success(mapOf("account_id" to prefs.getString("account_id", null), "revision" to prefs.getLong(REVISION, 0)))
    } }
    override fun onCancel(arguments: Any?) { dispose() }
    fun dispose() {
        listener?.let { prefs.unregisterOnSharedPreferenceChangeListener(it) }
        listener = null; sink = null
        handler.removeCallbacksAndMessages(null)
    }
    companion object {
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/checkpoint_delivery_events"
        const val REVISION = "delivery_revision"
    }
}
