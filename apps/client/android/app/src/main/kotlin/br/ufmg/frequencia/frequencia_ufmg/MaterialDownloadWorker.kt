package br.ufmg.frequencia.frequencia_ufmg

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.ActivityManager
import android.app.KeyguardManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.SystemClock
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.ForegroundInfo
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import org.json.JSONObject

class MaterialDownloadWorker(
    context: Context,
    parameters: WorkerParameters,
) : Worker(context, parameters) {
    private val startedAt = SystemClock.elapsedRealtime()
    private var activeSpec: MaterialDownloadSpec? = null
    private var stage = "input"
    private var downloadedBytes = 0L
    private var declaredBytes = -1L
    private var httpStatus = 0
    override fun doWork(): Result {
        val spec = try {
            MaterialDownloadSpec.fromWorkerInput(inputData.keyValueMap)
        } catch (_: IllegalArgumentException) {
            log("invalid_input")
            return Result.failure()
        }

        activeSpec = spec
        stage = if (MaterialDownloadExecution.usesScheduledJob(Build.VERSION.SDK_INT)) {
            "job_setup"
        } else {
            "foreground_setup"
        }
        try {
            setProgressAsync(progressData(spec, 0, spec.expectedSize)).get()
            updateNotification(spec, 0, spec.expectedSize)
        } catch (error: Exception) {
            val code = if (stage == "job_setup") "job_setup_failure" else "foreground_failure"
            log(code, error)
            return failure(spec, code)
        }
        log("started")
        val directory = File(applicationContext.filesDir, "moodle_materials/${spec.namespace}")
        if (!directory.exists() && !directory.mkdirs()) {
            log("directory_failure")
            applicationContext.getSystemService(NotificationManager::class.java)
                .cancel(spec.notificationId)
            return failure(spec, "directory_failure")
        }
        val destination = File(directory, spec.storedName)
        val temporary = File(directory, "${spec.storedName}.part")
        var connection: HttpsURLConnection? = null
        try {
            stage = "connect"
            connection = (URL(spec.source).openConnection() as HttpsURLConnection).apply {
                instanceFollowRedirects = false
                connectTimeout = 15_000
                readTimeout = 30_000
                requestMethod = "GET"
                setRequestProperty("User-Agent", "FrequenciaUFMG-Android")
            }
            val status = connection.responseCode
            httpStatus = status
            stage = "response_headers"
            if (status in 500..599) return retryOrFail(spec, "upstream_$status")
            if (status != HttpURLConnection.HTTP_OK) {
                log("upstream_$status")
                return failure(spec, "upstream_$status")
            }
            val declared = connection.contentLengthLong
            declaredBytes = declared
            if (declared > MaterialDownloadSpec.MAX_FILE_BYTES) {
                log("declared_too_large")
                return failure(spec, "declared_too_large", total = declared)
            }
            var total = 0L
            var lastReportedBytes = 0L
            var lastReportedPercent = -1
            val progressTotal = if (declared >= 0) declared else spec.expectedSize
            stage = "body_read"
            connection.inputStream.use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        if (isStopped) throw DownloadCancelled()
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        downloadedBytes = total
                        if (total > MaterialDownloadSpec.MAX_FILE_BYTES) {
                            throw FileTooLarge()
                        }
                        output.write(buffer, 0, count)
                        val percent = if (progressTotal > 0) {
                            ((total * 100) / progressTotal).coerceIn(0, 100).toInt()
                        } else {
                            -1
                        }
                        if (
                            (percent != lastReportedPercent && percent >= 0) ||
                            (progressTotal <= 0 &&
                                total - lastReportedBytes >= PROGRESS_STEP_BYTES)
                        ) {
                            reportProgress(spec, total, progressTotal)
                            lastReportedBytes = total
                            lastReportedPercent = percent
                        }
                    }
                }
            }
            stage = "body_complete"
            if (isStopped) throw DownloadCancelled()
            if (!MaterialDownloadSpec.isCompleteBody(declared, total, connection.contentEncoding)) {
                return retryOrFail(spec, "incomplete_body")
            }
            stage = "file_commit"
            if (destination.exists() && !destination.delete()) throw IOException("replace")
            if (!temporary.renameTo(destination)) temporary.copyTo(destination, overwrite = true)
            temporary.delete()
            stage = "index_commit"
            MaterialCacheIndex.record(directory, spec, total)
            stage = "completed"
            log("completed")
            return Result.success(progressData(spec, total, total))
        } catch (_: DownloadCancelled) {
            log("cancelled")
            return failure(spec, "cancelled")
        } catch (_: FileTooLarge) {
            log("body_too_large")
            return failure(spec, "body_too_large")
        } catch (_: SocketTimeoutException) {
            return retryOrFail(spec, "timeout")
        } catch (error: IOException) {
            log("io_exception", error)
            return retryOrFail(spec, "io_failure")
        } finally {
            connection?.disconnect()
            temporary.delete()
            applicationContext.getSystemService(NotificationManager::class.java)
                .cancel(spec.notificationId)
        }
    }

    private fun retryOrFail(spec: MaterialDownloadSpec, code: String): Result {
        log(code)
        return if (runAttemptCount < 2) {
            Result.retry()
        } else {
            failure(spec, code)
        }
    }

    override fun onStopped() {
        log("stopped")
        activeSpec?.let {
            applicationContext.getSystemService(NotificationManager::class.java)
                .cancel(it.notificationId)
        }
        super.onStopped()
    }

    private fun failure(
        spec: MaterialDownloadSpec,
        code: String,
        total: Long = if (declaredBytes >= 0) declaredBytes else spec.expectedSize,
    ): Result = Result.success(progressData(spec, downloadedBytes, total, code))

    private fun reportProgress(spec: MaterialDownloadSpec, downloaded: Long, total: Long) {
        setProgressAsync(progressData(spec, downloaded, total))
        updateNotification(spec, downloaded, total)
    }

    private fun updateNotification(spec: MaterialDownloadSpec, downloaded: Long, total: Long) {
        val info = foregroundInfo(spec, downloaded, total)
        // Android 12+ runs expedited work through JobScheduler, without a service.
        // Starting an FGS here is illegal once the user leaves the app, including
        // between chained files. Notifications do not require starting a service.
        MaterialDownloadExecution.updateNotification(
            Build.VERSION.SDK_INT,
            notify = {
                applicationContext.getSystemService(NotificationManager::class.java)
                    .notify(spec.notificationId, info.notification)
            },
            startForeground = { setForegroundAsync(info).get() },
            notificationDenied = { error ->
                log("notification_denied", error)
            },
        )
    }

    private fun progressData(
        spec: MaterialDownloadSpec,
        downloaded: Long,
        total: Long,
        failureCode: String = "",
    ) = androidx.work.Data.Builder()
        .putString("id", spec.id)
        .putString("name", spec.name)
        .putLong("downloaded", downloaded)
        .putLong("total", total)
        .putString("failure_code", failureCode)
        .putString("stage", stage)
        .putInt("attempt", runAttemptCount + 1)
        .putLong("elapsed_ms", SystemClock.elapsedRealtime() - startedAt)
        .putInt("http_status", httpStatus)
        .build()

    private fun foregroundInfo(
        spec: MaterialDownloadSpec,
        downloaded: Long,
        total: Long,
    ): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Downloads de materiais",
                    NotificationManager.IMPORTANCE_LOW,
                ),
            )
        }
        val knownTotal = total > 0
        val progress = if (knownTotal) ((downloaded * 100) / total).coerceIn(0, 100).toInt() else 0
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(applicationContext.applicationInfo.icon)
            .setContentTitle("Baixando material da UFMG")
            .setContentText(if (knownTotal) "${spec.name} · $progress%" else spec.name)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(100, progress, !knownTotal)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Cancelar",
                androidx.work.WorkManager.getInstance(applicationContext)
                    .createCancelPendingIntent(id),
            )
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(spec.notificationId, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(spec.notificationId, notification)
        }
    }

    private fun log(code: String, error: Throwable? = null) {
        val process = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(process)
        Log.i(TAG, JSONObject()
            .put("event", "material_download")
            .put("code", code)
            .put("work_id", id.toString())
            .put("file_id", activeSpec?.id)
            .put("file_name", activeSpec?.name)
            .put("stage", stage)
            .put("attempt", runAttemptCount + 1)
            .put("elapsed_ms", SystemClock.elapsedRealtime() - startedAt)
            .put("http_status", httpStatus)
            .put("received_bytes", downloadedBytes)
            .put("declared_bytes", declaredBytes)
            .put("error_type", error?.javaClass?.simpleName)
            .put("cause_type", error?.cause?.javaClass?.simpleName)
            .put("android_sdk", Build.VERSION.SDK_INT)
            .put("stop_reason", stopReason)
            .put("process_importance", process.importance)
            .put("screen_interactive", applicationContext.getSystemService(PowerManager::class.java).isInteractive)
            .put("keyguard_locked", applicationContext.getSystemService(KeyguardManager::class.java).isKeyguardLocked)
            .put("execution_mode", if (MaterialDownloadExecution.usesScheduledJob(Build.VERSION.SDK_INT)) "scheduled_job" else "foreground_service")
            .toString())
    }

    private class DownloadCancelled : IOException()
    private class FileTooLarge : IOException()

    companion object {
        private const val TAG = "MaterialDownload"
        private const val CHANNEL_ID = "material_downloads"
        private const val PROGRESS_STEP_BYTES = 256L * 1024L
    }
}
