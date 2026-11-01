package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import androidx.work.*
import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.appcheck.FirebaseAppCheck
import com.google.firebase.appcheck.playintegrity.PlayIntegrityAppCheckProviderFactory
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/** Reports in the checkpoint preferences are the durable outbox; jobs contain only a local key. */
object CheckpointDelivery {
    const val TAG = "attendance_checkpoint_delivery"
    const val ORIGIN = "https://starter-function-59hl.nyc.appwrite.run"
    fun enqueue(context: Context, report: JSONObject, replace: Boolean = true) {
        if (!report.optBoolean("delivery_enabled") || CheckpointDeliveryPolicy.acknowledged(report)) return
        if (!FirstCheckpointBridge.active(context, report.optString("account_id"))) return
        val reports = FirstCheckpointBridge(context).deliveryReports(report.getString("account_id"))
        val now = System.currentTimeMillis()
        val request = OneTimeWorkRequestBuilder<CheckpointDeliveryWorker>()
            .setInputData(workDataOf("store" to FirstCheckpointBridge.PREFIX + report.getString("operation_id")))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInitialDelay(maxOf(0, CheckpointDeliveryPolicy.readyAt(report, reports, now)-now), TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).addTag(TAG).build()
        val operation = WorkManager.getInstance(context).enqueueUniqueWork(CheckpointDeliveryPolicy.workName(report), if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, request)
        operation.result.addListener({
            try { operation.result.get() }
            catch (error: Exception) { enqueueFailure(context, report, error) }
        }, java.util.concurrent.Executor { it.run() })
    }
    fun enqueueSafely(context: Context, report: JSONObject, replace: Boolean = true) {
        try { enqueue(context, report, replace) }
        catch (error: Exception) { enqueueFailure(context, report, error) }
    }
    private fun enqueueFailure(context: Context, report: JSONObject, error: Exception) {
        val failure = CheckpointDeliveryPolicy.failureDetails(error)
        try {
            synchronized(FirstCheckpointBridge.LOCK) {
                val key = FirstCheckpointBridge.PREFIX + report.getString("operation_id")
                if (!FirstCheckpointBridge.active(context, report.optString("account_id"))) return@synchronized
                val prefs = context.getSharedPreferences(key, 0)
                if (!prefs.contains("report")) return@synchronized
                val current = JSONObject(prefs.getString("report", "{}")!!)
                if (CheckpointDeliveryPolicy.acknowledged(current)) return@synchronized
                current.put("delivery_status", "retry").put("delivery_stage", "enqueue")
                    .put("delivery_reason", "delivery_enqueue_failed").put("delivery_enqueue_failure", failure)
                check(prefs.edit().putString("report", current.toString()).commit())
                BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(current))
            }
        } catch (_: Exception) {
            BackgroundLocationProof.emit(JSONObject().put("event_stage", "delivery_enqueue")
                .put("operation_id", report.optString("operation_id")).put("status", "delivery_enqueue_failed")
                .put("course_id", report.optString("course_id")).put("session_id", report.optString("session_id"))
                .put("failure", failure))
        }
    }
}

/** Deferrable upload only: exact alarms and the foreground location service remain independent. */
class CheckpointDeliveryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val key = inputData.getString("store") ?: return Result.success()
        if (!key.matches(Regex("first_checkpoint_[a-f0-9-]{36}"))) return Result.success()
        val prefs = applicationContext.getSharedPreferences(key, 0)
        val seed = synchronized(FirstCheckpointBridge.LOCK) {
            JSONObject(prefs.getString("report", "{}")!!)
        }
        val account = seed.optString("account_id")
        if (!seed.optBoolean("delivery_enabled") || !FirstCheckpointBridge.active(applicationContext, account) ||
            CheckpointDeliveryPolicy.acknowledged(seed)) return Result.success()
        val reports = FirstCheckpointBridge(applicationContext).deliveryReports(account)
        if (CheckpointDeliveryPolicy.readyAt(seed, reports, System.currentTimeMillis()) > System.currentTimeMillis()) return Result.retry()
        val body = CheckpointDeliveryPolicy.payload(seed, reports)
        val knownOperations = reports.map { it.optString("operation_id") }.toSet()
        val attempt = seed.optInt("delivery_attempt", 0) + 1
        val started = System.currentTimeMillis()
        var stage = "identity"
        var stageStarted = started
        val timings = JSONObject()
        fun record(outcome: String, reason: String, httpStatus: Int? = null) {
            synchronized(FirstCheckpointBridge.LOCK) {
                if (!FirstCheckpointBridge.active(applicationContext, account)) return@synchronized
                val index = applicationContext.getSharedPreferences(FirstCheckpointBridge.INDEX, 0)
                for (store in index.getStringSet("stores", emptySet())!!) {
                    val saved = applicationContext.getSharedPreferences(store, 0)
                    val r = JSONObject(saved.getString("report", "{}")!!)
                    if (r.optString("account_id") != account || !FirstCheckpointPolicy.sameRevision(seed, r) || r.optString("operation_id") !in knownOperations) continue
                    if (CheckpointDeliveryPolicy.acknowledged(r) && outcome in listOf("sending", "retry")) continue
                    r.put("delivery_status", outcome).put("delivery_reason", reason.take(120))
                        .put("delivery_attempt", attempt).put("delivery_worker_attempt", runAttemptCount+1).put("delivery_request_id", id.toString())
                        .put("delivery_stage", stage).put("delivery_updated_at_ms", System.currentTimeMillis())
                        .put("delivery_duration_ms", System.currentTimeMillis()-started).put("delivery_timings", timings)
                    r.remove("delivery_http_status")
                    if (httpStatus != null) r.put("delivery_http_status", httpStatus)
                    check(saved.edit().putString("report", r.toString()).commit())
                    BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(r))
                }
            }
        }
        var connection: HttpURLConnection? = null
        try {
            record("sending", "upload_started")
            FirebaseApp.initializeApp(applicationContext)
            val user = FirebaseAuth.getInstance().currentUser
            if (user == null || user.uid != account) {
                record("retry", "identity_unavailable")
                return Result.retry()
            }
            var clock = System.currentTimeMillis()
            val identity = Tasks.await(user.getIdToken(runAttemptCount > 0), 20, TimeUnit.SECONDS).token
                ?: error("identity_token_unavailable")
            timings.put("identity_ms", System.currentTimeMillis()-clock)
            stage = "app_check"
            clock = System.currentTimeMillis()
            stageStarted = clock
            val appCheck = FirebaseAppCheck.getInstance()
            appCheck.installAppCheckProviderFactory(PlayIntegrityAppCheckProviderFactory.getInstance())
            val attestation = Tasks.await(appCheck.getLimitedUseAppCheckToken(), 20, TimeUnit.SECONDS).token
            timings.put("app_check_ms", System.currentTimeMillis()-clock)
            if (isStopped || !FirstCheckpointBridge.active(applicationContext, account)) return Result.success()
            val latest = FirstCheckpointBridge(applicationContext).deliveryReports(account)
            if (CheckpointDeliveryPolicy.payload(seed, latest).toString() != body.toString()) return Result.success()
            stage = "http"
            clock = System.currentTimeMillis()
            stageStarted = clock
            val course = seed.getString("course_id"); val session = seed.getString("session_id")
            require(course.matches(Regex("[A-Za-z0-9_-]{1,128}")) && session.matches(Regex("[A-Za-z0-9_-]{1,128}")))
            connection = URL("${CheckpointDelivery.ORIGIN}/v1/courses/$course/sessions/$session/checkpoints").openConnection() as HttpURLConnection
            connection.requestMethod = "PUT"; connection.instanceFollowRedirects = false
            connection.connectTimeout = 10000; connection.readTimeout = 25000; connection.doOutput = true
            connection.setRequestProperty("Authorization", "Bearer $identity")
            connection.setRequestProperty("X-Firebase-AppCheck", attestation)
            connection.setRequestProperty("X-Request-Id", id.toString())
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            timings.put("http_status", status).put("response_content_type", connection.contentType?.take(120) ?: "unknown")
            val serverRequest = connection.getHeaderField("X-Request-ID")
            if (serverRequest != null && serverRequest.matches(Regex("[A-Za-z0-9._-]{1,96}"))) timings.put("server_request_id", serverRequest)
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val bytes = stream?.use { input ->
                val output = ByteArrayOutputStream(); val buffer = ByteArray(4096)
                while (output.size() <= 32768) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: byteArrayOf()
            timings.put("http_ms", System.currentTimeMillis()-clock).put("response_bytes", bytes.size)
            stage = "response_decode"
            stageStarted = System.currentTimeMillis()
            check(bytes.size <= 32768) { "response_too_large" }
            val response = JSONObject(String(bytes, Charsets.UTF_8))
            stage = "confirmation"
            val outcome = CheckpointDeliveryPolicy.confirmedOutcome(status, response, body)
            val confirmationMismatch = status == 200 && outcome == "retry" && response.optString("outcome") !in listOf("waiting", "")
            val reason = if (confirmationMismatch) "confirmation_mismatch" else response.optString("reason", response.optString("error", "unexpected_response"))
            record(outcome, reason, status)
            return if (outcome == "retry") Result.retry() else Result.success()
        } catch (error: Exception) {
            timings.put("failed_stage", stage).put(stage + "_ms", System.currentTimeMillis()-stageStarted)
                .put("failure", CheckpointDeliveryPolicy.failureDetails(error))
            record("retry", error.cause?.javaClass?.simpleName ?: error.javaClass.simpleName, if (timings.has("http_status")) timings.getInt("http_status") else null)
            return Result.retry()
        } finally { connection?.disconnect() }
    }
}
