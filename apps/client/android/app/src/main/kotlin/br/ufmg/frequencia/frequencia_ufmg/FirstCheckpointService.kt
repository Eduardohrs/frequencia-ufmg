package br.ufmg.frequencia.frequencia_ufmg

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/** Bounded one-shot capture. No persistent tracking and no attendance/cloud writes. */
class FirstCheckpointService : Service() {
    private val executor = Executors.newSingleThreadExecutor()
    private val pending = AtomicInteger()
    private val wakeLocks = ConcurrentHashMap<String, PowerManager.WakeLock>()
    @Volatile private var latestStartId = 0
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        latestStartId = startId
        val key = intent?.data?.lastPathSegment
        if (intent?.action != "capture_first_checkpoint" || key == null ||
            !key.matches(Regex("first_checkpoint_[a-f0-9-]{36}"))) {
            if (pending.get() == 0) stopSelfResult(startId)
            return START_NOT_STICKY
        }
        // Start foreground immediately to satisfy Android's service deadline, even if the report expired.
        try {
            val notifications = getSystemService(NotificationManager::class.java)
            val channel = "attendance_location_check"
            if (Build.VERSION.SDK_INT >= 26) notifications.createNotificationChannel(
                NotificationChannel(channel, "Verificação de localização", NotificationManager.IMPORTANCE_LOW))
            val notification = NotificationCompat.Builder(this, channel)
                .setSmallIcon(applicationInfo.icon).setContentTitle("Verificando primeiro ping")
                .setContentText("Verificação temporária de localização. Não altera sua frequência.")
                .setOngoing(true).setOnlyAlertOnce(true)
                .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE).build()
            if (Build.VERSION.SDK_INT >= 29) startForeground(48001, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            else startForeground(48001, notification)
        } catch (error: Exception) {
            FirstCheckpointBridge(this).fail(key, "foreground_service_start_failed", "alarm_dispatch", error)
            if (pending.get() == 0) stopSelfResult(startId)
            return START_NOT_STICKY
        }
        val report = FirstCheckpointBridge(this).dispatch(key) ?: run {
            finishIfIdle(); return START_NOT_STICKY
        }
        // Duplicate delivery must not launch concurrent captures for the same operation.
        val capture = BackgroundLocationCapture(applicationContext, report.getString("operation_id"), key, 1) { }
        if (captures.putIfAbsent(key, capture) != null) return START_NOT_STICKY
        pending.incrementAndGet()
        val wake = getSystemService(PowerManager::class.java).newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK, "frequencia:first-checkpoint")
        wake.setReferenceCounted(false)
        wake.acquire(120000)
        wakeLocks[key] = wake
        executor.execute {
            try { capture.run() }
            finally {
                captures.remove(key, capture)
                wakeLocks.remove(key, wake)
                if (wake.isHeld) wake.release()
                pending.decrementAndGet()
                android.os.Handler(mainLooper).post { finishIfIdle() }
            }
        }
        return START_NOT_STICKY
    }
    private fun finishIfIdle() {
        if (pending.get() == 0) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelfResult(latestStartId)
        }
    }
    override fun onDestroy() {
        captures.values.forEach { it.cancel() }
        captures.clear()
        executor.shutdownNow()
        wakeLocks.values.forEach { if (it.isHeld) it.release() }
        wakeLocks.clear()
        super.onDestroy()
    }
    companion object {
        private val captures = ConcurrentHashMap<String, BackgroundLocationCapture>()
        fun cancel(key: String) { captures[key]?.cancel() }
    }
}
