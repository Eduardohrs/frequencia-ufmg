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
import androidx.core.os.CancellationSignal
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
            .put("event", "background_location_proof").toString()) }
        fun JSONObject.toMap(): Map<String, Any> = keys().asSequence().associateWith { get(it) }
    }
}

class BackgroundLocationProofWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
    @Volatile private var activeSignal: CancellationSignal? = null
    @Volatile private var activeLatch: CountDownLatch? = null
    override fun onStopped() {
        activeSignal?.cancel()
        activeLatch?.countDown()
    }
    override fun doWork(): Result {
        val context = applicationContext
        val prefs = context.getSharedPreferences(BackgroundLocationProof.STORE, 0)
        val report = try { JSONObject(prefs.getString("report", "{}")!!) } catch (error: Exception) {
            BackgroundLocationProof.emit(JSONObject().put("operation_id", id.toString())
                .put("status", "invalid_report").put("stage", "report_read")
                .put("cause_type", error.javaClass.simpleName))
            return Result.failure()
        }
        // A superseded request must not overwrite another diagnostic report.
        if (report.optString("operation_id") != id.toString()) return Result.success()
        val startedAtNanos = SystemClock.elapsedRealtimeNanos()
        val start = SystemClock.elapsedRealtime()
        var stage = "permissions"
        fun save(status: String): Result {
            if (JSONObject(prefs.getString("report", "{}")!!).optString("operation_id") != id.toString()) return Result.success()
            report.put("status", status).put("stage", stage).put("updated_at_ms", System.currentTimeMillis())
                .put("duration_ms", SystemClock.elapsedRealtime() - start)
            val persisted = prefs.edit().putString("report", report.toString()).commit()
            report.put("persisted", persisted)
            BackgroundLocationProof.emit(report)
            return if (persisted) Result.success() else Result.failure()
        }
        fun granted(permission: String) = ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
        fun state(suffix: String) {
            val info = ActivityManager.RunningAppProcessInfo()
            ActivityManager.getMyMemoryState(info)
            report.put("screen_locked_$suffix", context.getSystemService(KeyguardManager::class.java).isKeyguardLocked)
                .put("process_importance_$suffix", info.importance)
                .put("background_$suffix", info.importance > ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND)
        }
        try {
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
            report.put("battery_unrestricted", unrestricted).put("run_attempt", runAttemptCount + 1)
            val visible = !report.optBoolean("background_start") && !report.optBoolean("screen_locked_start")
            if (!BackgroundProofPolicy.canStartForegroundCapture(Build.VERSION.SDK_INT, unrestricted, visible)) {
                return save("battery_optimization_required")
            }
            save("running")
            val foregroundStarted = SystemClock.elapsedRealtime()
            setForegroundAsync(foregroundInfo()).get(10, TimeUnit.SECONDS)
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
                val attemptStarted = SystemClock.elapsedRealtime()
                save("running")
                val latch = CountDownLatch(1)
                val reading = AtomicReference<Location?>()
                val signal = CancellationSignal()
                activeSignal = signal
                activeLatch = latch
                val completed: Boolean
                try {
                    LocationManagerCompat.getCurrentLocation(manager, provider, signal,
                        ContextCompat.getMainExecutor(context)) { fix -> reading.set(fix); latch.countDown() }
                    completed = latch.await(20, TimeUnit.SECONDS)
                } finally {
                    signal.cancel()
                    activeSignal = null
                    activeLatch = null
                }
                if (isStopped) return save("interrupted")
                val fix = reading.get()
                lastFailure = when {
                    !completed -> "location_timeout"
                    fix == null -> "location_unavailable"
                    else -> BackgroundProofPolicy.fix(
                        (SystemClock.elapsedRealtimeNanos() - fix.elapsedRealtimeNanos) / 1000000,
                        fix.accuracy, fix.elapsedRealtimeNanos >= startedAtNanos) ?: "succeeded"
                }
                report.put("${provider}_outcome", lastFailure)
                    .put("${provider}_duration_ms", SystemClock.elapsedRealtime() - attemptStarted)
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
