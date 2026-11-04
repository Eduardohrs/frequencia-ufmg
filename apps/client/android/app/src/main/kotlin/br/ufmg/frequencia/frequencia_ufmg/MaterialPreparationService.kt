package br.ufmg.frequencia.frequencia_ufmg

import android.app.ActivityManager
import android.app.KeyguardManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.ResultReceiver
import android.os.SystemClock
import android.util.Log
import androidx.core.app.ServiceCompat
import org.json.JSONObject

/** User-started preparation scope, acquired BEFORE any asynchronous metadata request. */
class MaterialPreparationService : Service() {
    private data class Scope(val namespace: String, val operation: String, val count: Int, val started: Long)
    private val scopes = mutableMapOf<String, Scope>()
    private val handler = Handler(Looper.getMainLooper())
    private val namespaces = mutableSetOf<String>()
    private var wakeLock: PowerManager.WakeLock? = null
    private val expire = Runnable { stopScopes("lease_timeout") }

    override fun onCreate() {
        super.onCreate()
        instance = this
        handler.postDelayed(expire, MAX_DURATION_MS)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        @Suppress("DEPRECATION")
        val receiver = intent?.getParcelableExtra<ResultReceiver>("ready")
        val session = intent?.getStringExtra("session_id")
        if (session == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        val scope = Scope(
            intent.getStringExtra("namespace") ?: "",
            intent.getStringExtra("operation_id") ?: session,
            intent.getIntExtra("material_count", 0),
            SystemClock.elapsedRealtime(),
        )
        try {
            val notification = MaterialDownloadNotifications.preparation(this)
            ServiceCompat.startForeground(this, MaterialDownloadNotifications.id(scope.namespace), notification,
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0,
            )
            namespaces.add(scope.namespace)
            if (wakeLock == null) {
                wakeLock = getSystemService(PowerManager::class.java)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "frequencia:material_preparation")
                    .apply { setReferenceCounted(false); acquire(MAX_DURATION_MS) }
            }
            scopes[session] = scope
            MaterialDownloadNotifications.refresh(this,scope.namespace)
            log(session, scope, "ready")
            // The Dart requests must not run until Android has accepted foreground execution.
            receiver?.send(0, null)
        } catch (error: Exception) {
            log(session, scope, "start_failed", error)
            receiver?.send(1, android.os.Bundle().apply {
                putString("cause_type", error.javaClass.simpleName)
                putString("cause_message", error.message?.take(600))
            })
            if (scopes.isEmpty()) stopSelf()
        }
        // No orphan service is restarted without its original Flutter work.
        return START_NOT_STICKY
    }

    private fun finish(session: String) {
        scopes.remove(session)?.let { log(session, it, "released"); MaterialDownloadNotifications.refresh(this,it.namespace) }
        if (scopes.isEmpty()) stopSelf()
    }

    private fun stopScopes(reason: String) {
        scopes.forEach { (id, scope) -> log(id, scope, reason) }
        scopes.clear()
        stopSelf()
    }

    override fun onTaskRemoved(rootIntent: Intent?) { stopScopes("task_removed") }

    override fun onTimeout(startId: Int, fgsType: Int) { stopScopes("platform_timeout") }

    override fun onDestroy() {
        scopes.forEach { (id, scope) -> log(id, scope, "destroyed") }
        scopes.clear()
        handler.removeCallbacks(expire)
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        stopForeground(STOP_FOREGROUND_DETACH)
        namespaces.forEach { MaterialDownloadNotifications.refresh(this,it) }
        if (instance === this) instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun log(session: String, scope: Scope, code: String, error: Throwable? = null) {
        val process = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(process)
        Log.i("MaterialPreparation", JSONObject()
            .put("event", "material_preparation_scope")
            .put("code", code)
            .put("stage", "preparation_execution")
            .put("batch_id", session)
            .put("operation_id", scope.operation)
            .put("namespace", scope.namespace)
            .put("material_count", scope.count)
            .put("elapsed_ms", SystemClock.elapsedRealtime() - scope.started)
            .put("android_sdk", Build.VERSION.SDK_INT)
            .put("process_importance", process.importance)
            .put("screen_interactive", getSystemService(PowerManager::class.java).isInteractive)
            .put("keyguard_locked", getSystemService(KeyguardManager::class.java).isKeyguardLocked)
            .put("error_type", error?.javaClass?.simpleName)
            .put("error_message", error?.message?.take(600))
            .toString())
    }

    companion object {
        private const val MAX_DURATION_MS = 10L * 60L * 1000L
        private var instance: MaterialPreparationService? = null
        fun finish(session: String) { instance?.finish(session) }
        fun pendingCount(namespace: String): Int = instance?.scopes?.values?.filter { it.namespace == namespace }?.sumOf { it.count } ?: 0
    }
}
