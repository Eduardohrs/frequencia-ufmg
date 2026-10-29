package br.ufmg.frequencia.frequencia_ufmg

import android.Manifest
import android.app.ActivityManager
import android.app.KeyguardManager
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.SystemClock
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
                "read" -> result.success(JSONObject(context.getSharedPreferences(STORE, 0)
                    .getString("report", "{}")!!).toMap())
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
            report.put("started_at_ms", System.currentTimeMillis())
                .put("queue_wait_ms", System.currentTimeMillis() - report.optLong("scheduled_at_ms"))
                .put("android_sdk", Build.VERSION.SDK_INT)
            val manager = context.getSystemService(LocationManager::class.java)
            val precise = granted(Manifest.permission.ACCESS_FINE_LOCATION)
            val background = Build.VERSION.SDK_INT < 29 || granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            val services = LocationManagerCompat.isLocationEnabled(manager)
            report.put("precise_permission", precise).put("background_permission", background).put("location_services", services)
            BackgroundProofPolicy.blocked(precise, background, services)?.let { return save(it) }
            stage = "location_fix"
            save("running")
            val provider = when {
                manager.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
                manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
                else -> return save("provider_unavailable")
            }
            report.put("provider", provider).put("timeout_ms", 45000)
            val latch = CountDownLatch(1)
            val reading = AtomicReference<Location?>()
            val signal = CancellationSignal()
            activeSignal = signal
            activeLatch = latch
            try {
                LocationManagerCompat.getCurrentLocation(manager, provider, signal,
                    ContextCompat.getMainExecutor(context)) { location -> reading.set(location); latch.countDown() }
                if (!latch.await(45, TimeUnit.SECONDS)) return save("location_timeout")
            } finally {
                signal.cancel()
                activeSignal = null
                activeLatch = null
            }
            if (isStopped) return save("interrupted")
            val location = reading.get() ?: return save("location_unavailable")
            state("capture")
            val age = (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1000000
            report.put("fix_age_ms", age).put("accuracy_m", location.accuracy.toDouble())
                .put("fix_recorded_at_ms", location.time).put("captured_at_ms", System.currentTimeMillis())
            stage = "validation"
            val status = BackgroundProofPolicy.fix(age, location.accuracy, location.elapsedRealtimeNanos >= startedAtNanos) ?: "succeeded"
            report.put("background_proven", BackgroundProofPolicy.proven(status,
                report.optBoolean("screen_locked_start") || report.optBoolean("background_start"),
                report.optBoolean("screen_locked_capture") || report.optBoolean("background_capture")))
            return save(status)
        } catch (error: Exception) {
            report.put("cause_type", error.javaClass.simpleName).put("cause_message", error.message?.take(300))
            return save(if (error is SecurityException) "permission_revoked" else "provider_error")
        }
    }
}
