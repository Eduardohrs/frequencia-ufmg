package br.ufmg.frequencia.frequencia_ufmg

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
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

class MaterialDownloadWorker(
    context: Context,
    parameters: WorkerParameters,
) : Worker(context, parameters) {
    override fun doWork(): Result {
        val spec = try {
            MaterialDownloadSpec.from(
                mapOf(
                    "id" to inputData.getString("id"),
                    "name" to inputData.getString("name"),
                    "source" to inputData.getString("source"),
                    "expected_size" to inputData.getLong("expected_size", -1),
                    "mime_type" to inputData.getString("mime_type"),
                    "namespace" to inputData.getString("namespace"),
                ),
            )
        } catch (_: IllegalArgumentException) {
            log("invalid_input")
            return Result.failure()
        }

        try {
            setProgressAsync(progressData(spec, 0, spec.expectedSize)).get()
            setForegroundAsync(foregroundInfo(spec, 0, spec.expectedSize)).get()
        } catch (_: Exception) {
            log("foreground_failure")
            return failure(spec, "foreground_failure")
        }
        val directory = File(applicationContext.filesDir, "moodle_materials/${spec.namespace}")
        if (!directory.exists() && !directory.mkdirs()) {
            log("directory_failure")
            return failure(spec, "directory_failure")
        }
        val destination = File(directory, spec.storedName)
        val temporary = File(directory, "${spec.storedName}.part")
        var connection: HttpsURLConnection? = null
        try {
            connection = (URL(spec.source).openConnection() as HttpsURLConnection).apply {
                instanceFollowRedirects = false
                connectTimeout = 15_000
                readTimeout = 30_000
                requestMethod = "GET"
                setRequestProperty("User-Agent", "FrequenciaUFMG-Android")
            }
            val status = connection.responseCode
            if (status in 500..599) return retryOrFail(spec, "upstream_$status")
            if (status != HttpURLConnection.HTTP_OK) {
                log("upstream_$status")
                return failure(spec, "upstream_$status")
            }
            val declared = connection.contentLengthLong
            if (declared > MaterialDownloadSpec.MAX_FILE_BYTES) {
                log("declared_too_large")
                return failure(spec, "declared_too_large", total = declared)
            }
            var total = 0L
            var lastReportedBytes = 0L
            var lastReportedPercent = -1
            val progressTotal = maxOf(declared, spec.expectedSize)
            connection.inputStream.use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        if (isStopped) throw DownloadCancelled()
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
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
            if (destination.exists() && !destination.delete()) throw IOException("replace")
            if (!temporary.renameTo(destination)) temporary.copyTo(destination, overwrite = true)
            temporary.delete()
            MaterialCacheIndex.record(directory, spec, total)
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
        } catch (_: IOException) {
            return retryOrFail(spec, "io_failure")
        } finally {
            connection?.disconnect()
            temporary.delete()
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

    private fun failure(
        spec: MaterialDownloadSpec,
        code: String,
        total: Long = spec.expectedSize,
    ): Result = Result.success(progressData(spec, 0, total, code))

    private fun reportProgress(spec: MaterialDownloadSpec, downloaded: Long, total: Long) {
        setProgressAsync(progressData(spec, downloaded, total))
        setForegroundAsync(foregroundInfo(spec, downloaded, total))
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

    private fun log(code: String) {
        Log.i(TAG, "event=material_download code=$code work=${id.toString().take(8)}")
    }

    private class DownloadCancelled : IOException()
    private class FileTooLarge : IOException()

    companion object {
        private const val TAG = "MaterialDownload"
        private const val CHANNEL_ID = "material_downloads"
        private const val PROGRESS_STEP_BYTES = 256L * 1024L
    }
}
