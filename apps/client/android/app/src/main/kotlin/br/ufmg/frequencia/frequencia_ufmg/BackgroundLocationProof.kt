package br.ufmg.frequencia.frequencia_ufmg

import android.Manifest
import android.app.ActivityManager
import android.app.KeyguardManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.pm.ServiceInfo
import androidx.core.app.NotificationCompat
import androidx.work.ForegroundInfo
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.SystemClock
import android.os.PowerManager
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import androidx.core.location.LocationListenerCompat
import androidx.core.location.LocationRequestCompat
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Explicit diagnostic only: one sample, no attendance writes or recurring tracking. */
class BackgroundLocationProof(private val context: Context) {
    fun handle(method: String, result: MethodChannel.Result) {
        try {
            when (method) {
                "schedule" -> {
                    val request = OneTimeWorkRequestBuilder<BackgroundLocationProofWorker>()
                        .setInitialDelay(2, TimeUnit.MINUTES).build()
                    val report = JSONObject().put("operation_id", request.id.toString())
                        .put("status", "scheduled").put("scheduled_at_ms", System.currentTimeMillis())
                        .put("minimum_delay_ms", 120000)
                    check(context.getSharedPreferences(STORE, 0).edit().putString("report", report.toString()).commit())
                    // A new explicit diagnostic supersedes the previous one.
                    val enqueued = WorkManager.getInstance(context).enqueueUniqueWork(STORE, ExistingWorkPolicy.REPLACE, request)
                    enqueued.result.addListener({
                        try {
                            enqueued.result.get()
                            emit(report)
                            result.success(report.toMap())
                        } catch (error: Exception) {
                            report.put("status", "enqueue_failed").put("stage", "enqueue")
                                .put("cause_type", error.javaClass.simpleName)
                                .put("cause_message", error.message?.take(300))
                            context.getSharedPreferences(STORE, 0).edit().putString("report", report.toString()).apply()
                            emit(report)
                            result.error("background_proof_failed", "Não foi possível agendar o teste.", report.toMap())
                        }
                    }, ContextCompat.getMainExecutor(context))
                }
                "read" -> {
                    val report = JSONObject(context.getSharedPreferences(STORE, 0).getString("report", "{}")!!)
                    if (Build.VERSION.SDK_INT >= 30 && report.optString("status") == "running") {
                        try {
                            val workerPid = report.optInt("process_id")
                            if (workerPid > 0) {
                                val exit = context.getSystemService(ActivityManager::class.java)
                                    .getHistoricalProcessExitReasons(context.packageName, workerPid, 1).firstOrNull()
                                if (exit != null && BackgroundProofPolicy.interrupted(report.optString("status"), workerPid,
                                    android.os.Process.myPid(), exit.timestamp, report.optLong("started_at_ms"))) {
                                    report.put("status", "interrupted_process_exit").put("previous_status", "running")
                                        .put("process_exit_reason", exit.reason).put("process_exit_at_ms", exit.timestamp)
                                        .put("process_exit_description", exit.description?.take(300))
                                }
                            }
                        } catch (error: Exception) {
                            report.put("exit_lookup_error", error.javaClass.simpleName)
                        }
                    }
                    result.success(report.toMap())
                }
                else -> result.notImplemented()
            }
        } catch (error: Exception) {
            result.error("background_proof_failed", "Não foi possível preparar o teste.",
                mapOf("stage" to method, "cause_type" to error.javaClass.simpleName,
                    "cause_message" to error.message?.take(300)))
        }
    }
    companion object {
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/background_proof"
        const val STORE = "background_location_proof"
        fun emit(report: JSONObject) { Log.i("BackgroundLocationProof", JSONObject(report.toString())
            .put("event", if (report.optString("moment") == "first") "first_attendance_checkpoint" else "background_location_proof").toString()) }
        fun JSONObject.toMap(): Map<String, Any> = keys().asSequence().associateWith { get(it) }
    }
}

class BackgroundLocationProofWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
    private var capture: BackgroundLocationCapture? = null
    override fun onStopped() { capture?.cancel() }
    override fun doWork(): Result {
        // Old persisted checkpoint requests are migrated by the bridge/update receiver.
        // Never let a legacy JobScheduler delivery compete with an exact alarm.
        if (inputData.getString("checkpoint_store") != null) return Result.success()
        val runner = BackgroundLocationCapture(applicationContext, id.toString(),
            null, runAttemptCount + 1) {
            setForegroundAsync(foregroundInfo()).get(10, TimeUnit.SECONDS)
        }
        capture = runner
        if (isStopped) runner.cancel()
        return if (runner.run()) Result.success() else Result.failure()
    }
    private fun foregroundInfo(): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        val channel = "attendance_location_check"
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(channel, "Verificação de localização", NotificationManager.IMPORTANCE_LOW))
        }
        val notification = NotificationCompat.Builder(applicationContext, channel)
            .setSmallIcon(applicationContext.applicationInfo.icon)
            .setContentTitle("Verificando localização em segundo plano")
            .setContentText("Verificação temporária. Nenhuma presença será alterada.")
            .setOngoing(true).setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Cancelar",
                WorkManager.getInstance(applicationContext).createCancelPendingIntent(id))
            .build()
        return if (Build.VERSION.SDK_INT >= 29) {
            ForegroundInfo(47001, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else ForegroundInfo(47001, notification)
    }

}

/** The single capture implementation, shared by the diagnostic worker and exact alarm service. */
class BackgroundLocationCapture(
    private val context: Context,
    private val id: String,
    private val checkpointStore: String?,
    private val attempt: Int,
    private val enterForeground: () -> Unit,
) {
    @Volatile private var activeCancel: (() -> Unit)? = null
    @Volatile private var activeLatch: CountDownLatch? = null
    @Volatile private var isStopped = false
    fun cancel() {
        isStopped = true
        activeCancel?.invoke()
        activeLatch?.countDown()
    }
    fun run(): Boolean {
        if (checkpointStore != null && !checkpointStore.matches(Regex("first_checkpoint_[a-f0-9-]{36}"))) return false
        val prefs = context.getSharedPreferences(checkpointStore ?: BackgroundLocationProof.STORE, 0)
        val report = try { JSONObject(prefs.getString("report", "{}")!!) } catch (error: Exception) {
            BackgroundLocationProof.emit(JSONObject().put("operation_id", id.toString())
                .put("status", "invalid_report").put("stage", "report_read")
                .put("cause_type", error.javaClass.simpleName))
            return false
        }
        // A superseded request must not overwrite another diagnostic report.
        if (report.optString("operation_id") != id.toString()) return true
        val startedAtNanos = SystemClock.elapsedRealtimeNanos()
        val start = SystemClock.elapsedRealtime()
        var stage = "permissions"
        fun save(status: String): Boolean = synchronized(FirstCheckpointBridge.LOCK) {
            val current = JSONObject(prefs.getString("report", "{}")!!)
            if (current.optString("operation_id") != id.toString() || current.optString("status") in listOf("cancelled", "superseded")) return true
            if (checkpointStore != null && (!FirstCheckpointBridge.active(context, report.optString("account_id")) ||
                current.optString("status") !in listOf("scheduled", "running"))) return true
            report.put("status", status).put("stage", stage).put("updated_at_ms", System.currentTimeMillis())
                .put("duration_ms", SystemClock.elapsedRealtime() - start)
            val persisted = prefs.edit().putString("report", report.toString()).commit()
            report.put("persisted", persisted)
            BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(report))
            return persisted
        }
        fun granted(permission: String) = ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
        fun state(suffix: String) {
            val info = ActivityManager.RunningAppProcessInfo()
            ActivityManager.getMyMemoryState(info)
            report.put("screen_locked_$suffix", context.getSystemService(KeyguardManager::class.java).isKeyguardLocked)
                .put("process_importance_$suffix", info.importance)
                .put("background_$suffix", info.importance > ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND)
        }
        if (checkpointStore != null && report.optString("status") !in listOf("scheduled", "running")) return true
        try {
            if (checkpointStore != null) {
                if (!FirstCheckpointBridge.active(context, report.optString("account_id"))) return true
                report.put("lateness_ms", System.currentTimeMillis() - report.getLong("checkpoint_expected_at_ms"))
                if (FirstCheckpointPolicy.late(report, System.currentTimeMillis())) return save("checkpoint_outside_window")
            }
            state("start")
            report.put("started_at_ms", System.currentTimeMillis()).put("process_id", android.os.Process.myPid())
                .put("queue_wait_ms", System.currentTimeMillis() - report.optLong("scheduled_at_ms"))
                .put("android_sdk", Build.VERSION.SDK_INT)
            val manager = context.getSystemService(LocationManager::class.java)
            val precise = granted(Manifest.permission.ACCESS_FINE_LOCATION)
            val background = Build.VERSION.SDK_INT < 29 || granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            val services = LocationManagerCompat.isLocationEnabled(manager)
            report.put("precise_permission", precise).put("background_permission", background).put("location_services", services)
            BackgroundProofPolicy.blocked(precise, background, services)?.let { return save(it) }
            val power = context.getSystemService(PowerManager::class.java)
            stage = "foreground_service"
            val unrestricted = power.isIgnoringBatteryOptimizations(context.packageName)
            report.put("battery_unrestricted", unrestricted).put("run_attempt", attempt)
            val visible = !report.optBoolean("background_start") && !report.optBoolean("screen_locked_start")
            if (!BackgroundProofPolicy.canStartForegroundCapture(Build.VERSION.SDK_INT, unrestricted, visible)) {
                return save("battery_optimization_required")
            }
            save("running")
            val foregroundStarted = SystemClock.elapsedRealtime()
            enterForeground()
            // Wait for the OS to apply foreground importance before requesting a fix.
            var importance: Int
            do {
                if (isStopped) return save("interrupted")
                val process = ActivityManager.RunningAppProcessInfo()
                ActivityManager.getMyMemoryState(process)
                importance = process.importance
                if (importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE) break
                Thread.sleep(50)
            } while (SystemClock.elapsedRealtime() - foregroundStarted < 5000)
            report.put("foreground_service_duration_ms", SystemClock.elapsedRealtime() - foregroundStarted)
                .put("foreground_service_importance", importance)
            if (importance > ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE) {
                return save("foreground_service_unavailable")
            }
            report.put("foreground_service_active", true)
            stage = "location_fix"
            save("running")
            val mode = if (Build.VERSION.SDK_INT >= 28) power.locationPowerSaveMode else 0
            val gps = manager.isProviderEnabled(LocationManager.GPS_PROVIDER)
            val network = manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
            report.put("power_save_mode", power.isPowerSaveMode).put("location_power_save_mode", mode)
                .put("interactive", power.isInteractive)
                .put("battery_unrestricted", power.isIgnoringBatteryOptimizations(context.packageName))
                .put("gps_enabled", gps).put("network_enabled", network)
            val providers = BackgroundProofPolicy.providers(gps, network, mode, power.isInteractive,
                report.optBoolean("foreground_service_active") || !report.optBoolean("background_start"))
            if (providers.isEmpty()) return save(if (gps || network) "power_save_location_blocked" else "provider_unavailable")
            var location: Location? = null
            var lastFailure = "location_unavailable"
            for ((index, provider) in providers.withIndex()) {
                if (isStopped) return save("interrupted")
                report.put("provider", provider).put("provider_attempt", index + 1).put("provider_timeout_ms", 20000)
                    .put("location_request_mode", "fresh_updates")
                val attemptStarted = SystemClock.elapsedRealtime()
                save("running")
                val latch = CountDownLatch(1)
                val reading = AtomicReference<Location?>()
                val gate = FreshFixWindow(startedAtNanos)
                val listener = object : LocationListenerCompat {
                    override fun onLocationChanged(fix: Location) {
                        if (isStopped || latch.count == 0L) return
                        reading.set(fix)
                        if (gate.offer(fix.elapsedRealtimeNanos, SystemClock.elapsedRealtimeNanos(), fix.accuracy)) latch.countDown()
                    }
                    override fun onProviderDisabled(name: String) { latch.countDown() }
                }
                activeCancel = { LocationManagerCompat.removeUpdates(manager, listener) }
                activeLatch = latch
                val completed: Boolean
                try {
                    LocationManagerCompat.requestLocationUpdates(manager, provider,
                        LocationRequestCompat.Builder(1000).setDurationMillis(20000)
                            .setQuality(LocationRequestCompat.QUALITY_HIGH_ACCURACY).build(),
                        ContextCompat.getMainExecutor(context), listener)
                    completed = latch.await(20, TimeUnit.SECONDS)
                } finally {
                    LocationManagerCompat.removeUpdates(manager, listener)
                    activeCancel = null
                    activeLatch = null
                }
                if (isStopped) return save("interrupted")
                val fix = reading.get()
                lastFailure = if (fix == null) {
                    if (completed) "location_unavailable" else "location_timeout"
                } else gate.lastFailure ?: "succeeded"
                report.put("${provider}_outcome", lastFailure)
                    .put("${provider}_duration_ms", SystemClock.elapsedRealtime() - attemptStarted)
                    .put("${provider}_sample_count", gate.sampleCount)
                    .put("${provider}_rejected_count", gate.rejectedCount)
                if (fix != null) report.put("${provider}_fix_age_ms",
                    (SystemClock.elapsedRealtimeNanos() - fix.elapsedRealtimeNanos) / 1000000)
                    .put("${provider}_accuracy_m", if (fix.accuracy.isFinite()) fix.accuracy.toDouble() else "non_finite")
                if (lastFailure == "succeeded") { location = fix; break }
                save("running")
            }
            val fix = location ?: return save(lastFailure)
            state("capture")
            val age = (SystemClock.elapsedRealtimeNanos() - fix.elapsedRealtimeNanos) / 1000000
            report.put("fix_age_ms", age).put("accuracy_m", fix.accuracy.toDouble())
                .put("fix_recorded_at_ms", fix.time).put("captured_at_ms", System.currentTimeMillis())
            stage = "validation"
            val status = BackgroundProofPolicy.fix(age, fix.accuracy, fix.elapsedRealtimeNanos >= startedAtNanos) ?: "succeeded"
            if (checkpointStore != null) {
                report.put("lateness_ms", System.currentTimeMillis() - report.getLong("checkpoint_expected_at_ms"))
                if (FirstCheckpointPolicy.late(report, System.currentTimeMillis())) return save("checkpoint_outside_window")
                report.put("first_ping", FirstCheckpointPolicy.classify(report, fix.latitude, fix.longitude))
            }
            report.put("background_proven", BackgroundProofPolicy.proven(status,
                report.optBoolean("screen_locked_start") || report.optBoolean("background_start"),
                report.optBoolean("screen_locked_capture") || report.optBoolean("background_capture")))
            return save(status)
        } catch (error: Exception) {
            report.put("cause_type", error.javaClass.simpleName).put("cause_message", error.message?.take(300))
                .put("root_cause_type", error.cause?.javaClass?.simpleName)
                .put("root_cause_message", error.cause?.message?.take(300))
            return save(when {
                error is InterruptedException -> "interrupted"
                stage == "foreground_service" -> "foreground_service_start_failed"
                error is SecurityException -> "permission_revoked"
                else -> "provider_error"
            })
        }
    }
}
