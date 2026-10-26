package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ResultReceiver
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.core.content.ContextCompat
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.TimeUnit

class MaterialDownloadBridge(private val context: Context) {
    private val workManager = WorkManager.getInstance(context)

    fun handle(method: String, rawArguments: Any?, result: MethodChannel.Result) {
        try {
            val arguments = rawArguments as? Map<*, *> ?: emptyMap<Any, Any>()
            when (method) {
                "beginPreparation" -> beginPreparation(arguments, result)
                "endPreparation" -> {
                    MaterialPreparationService.finish(requireString(arguments, "session_id", 96))
                    result.success(null)
                }
                "enqueue" -> {
                    enqueue(MaterialDownloadSpec.from(arguments))
                    result.success(null)
                }
                "listQueue" -> listQueue(arguments, result)
                "dismiss" -> {
                    dismiss(arguments)
                    result.success(null)
                }
                "cancel" -> {
                    cancel(arguments)
                    result.success(null)
                }
                "cancelAll" -> {
                    cancelAll(arguments)
                    result.success(null)
                }
                else -> {
                    result.notImplemented()
                    return
                }
            }
        } catch (_: IllegalArgumentException) {
            result.error("invalid_material_download", "Dados de download inválidos.", null)
        }
    }

    private fun beginPreparation(arguments: Map<*, *>, result: MethodChannel.Result) {
        val namespace = requireNamespace(arguments)
        val session = requireString(arguments, "session_id", 96)
        require(Regex("^[A-Za-z0-9-]+$").matches(session))
        val operation = requireString(arguments, "operation_id", 128)
        val count = (arguments["material_count"] as? Number)?.toInt() ?: 0
        require(count in 1..1000)
        val handler = Handler(Looper.getMainLooper())
        var answered = false
        val timeout = Runnable {
            if (!answered) {
                answered = true
                MaterialPreparationService.finish(session)
                result.error("material_preparation_start_timeout", "O Android não confirmou o início da preparação.",
                    mapOf("stage" to "foreground_ack", "batch_id" to session))
            }
        }
        val receiver = object : ResultReceiver(handler) {
            override fun onReceiveResult(code: Int, data: Bundle?) {
                if (answered) { MaterialPreparationService.finish(session); return }
                answered = true
                handler.removeCallbacks(timeout)
                if (code == 0) result.success(null)
                else result.error("material_preparation_start_denied", "O Android recusou a preparação em segundo plano.",
                    mapOf("stage" to "foreground_ack", "batch_id" to session,
                        "cause_type" to data?.getString("cause_type"), "cause_message" to data?.getString("cause_message")))
            }
        }
        handler.postDelayed(timeout, 10_000)
        try {
            ContextCompat.startForegroundService(context, Intent(context, MaterialPreparationService::class.java)
                .putExtra("namespace", namespace)
                .putExtra("session_id", session)
                .putExtra("operation_id", operation)
                .putExtra("material_count", count)
                .putExtra("ready", receiver))
        } catch (error: Exception) {
            answered = true
            handler.removeCallbacks(timeout)
            result.error("material_preparation_start_failed", "Não foi possível iniciar a preparação.",
                mapOf("stage" to "service_launch", "batch_id" to session,
                    "cause_type" to error.javaClass.simpleName, "cause_message" to error.message?.take(600)))
        }
    }

    private fun listQueue(arguments: Map<*, *>, result: MethodChannel.Result) {
        val namespace = requireNamespace(arguments)
        val dismissed = dismissedIds(namespace)
        val future = workManager.getWorkInfosByTag(namespaceTag(namespace))
        future.addListener(
            {
                try {
                    result.success(
                        // WorkManager retains old failures after a successful retry.
                        // Show the latest request, not every historical attempt.
                        future.get().sortedByDescending {
                            MaterialDownloadExecution.queuedAt(it.tags)
                        }.map(::progressMap).filter {
                            (it["id"] as String).isNotEmpty()
                        }.distinctBy {
                            it["id"]
                        }.filterNot {
                            dismissed.contains(it["id"] as String)
                        },
                    )
                } catch (_: Exception) {
                    result.error("material_download_status", "Não foi possível consultar os downloads.", null)
                }
            },
            ContextCompat.getMainExecutor(context),
        )
    }

    private fun progressMap(info: WorkInfo): Map<String, Any> {
        val progress = if (info.state.isFinished) info.outputData else info.progress
        val failureCode = progress.getString("failure_code") ?: ""
        return mapOf(
            "id" to (progress.getString("id") ?: info.tags.firstOrNull {
                it.startsWith("material-id-")
            }?.removePrefix("material-id-") ?: ""),
            "name" to (progress.getString("name") ?: info.tags.firstOrNull {
                it.startsWith("material-name-")
            }?.removePrefix("material-name-") ?: "Material"),
            "state" to if (failureCode.isEmpty()) info.state.name.lowercase() else "failed",
            "downloaded" to progress.getLong("downloaded", 0),
            "total" to progress.getLong("total", 0),
            "failureCode" to failureCode,
            "stage" to (progress.getString("stage") ?: "native_worker"),
            "workId" to info.id.toString(),
            "attempt" to progress.getInt("attempt", 0),
            "elapsedMs" to progress.getLong("elapsed_ms", 0),
            "httpStatus" to progress.getInt("http_status", 0),
        )
    }

    private fun enqueue(spec: MaterialDownloadSpec) {
        setDismissed(spec.namespace, spec.id, dismissed = false)
        val request = OneTimeWorkRequestBuilder<MaterialDownloadWorker>()
            .setInputData(
                Data.Builder()
                    .putAll(spec.workerInput())
                    .build(),
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .apply {
                if (MaterialDownloadExecution.usesScheduledJob(Build.VERSION.SDK_INT)) {
                    setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                }
            }
            .addTag(namespaceTag(spec.namespace))
            .addTag(spec.itemTag)
            .addTag("material-queued-at-${System.currentTimeMillis()}")
            .addTag("material-id-${spec.id}")
            .addTag("material-name-${spec.name}")
            .build()
        workManager.beginUniqueWork(
            spec.queueWorkName,
            ExistingWorkPolicy.APPEND_OR_REPLACE,
            request,
        ).enqueue()
    }

    private fun cancel(arguments: Map<*, *>) {
        val id = requireString(arguments, "id", 512)
        val namespace = requireNamespace(arguments)
        setDismissed(namespace, id, dismissed = true)
        val itemTag = MaterialDownloadSpec.uniqueWorkName(namespace, id)
        workManager.cancelAllWorkByTag(itemTag)
    }

    private fun dismiss(arguments: Map<*, *>) {
        val id = requireString(arguments, "id", 512)
        val namespace = requireNamespace(arguments)
        setDismissed(namespace, id, dismissed = true)
    }

    private fun dismissedIds(namespace: String): Set<String> =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .getStringSet(dismissedKey(namespace), emptySet())
            ?.toSet() ?: emptySet()

    private fun setDismissed(namespace: String, id: String, dismissed: Boolean) {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val ids = preferences.getStringSet(dismissedKey(namespace), emptySet())
            ?.toMutableSet() ?: mutableSetOf()
        if (dismissed) ids.add(id) else ids.remove(id)
        preferences.edit().putStringSet(dismissedKey(namespace), ids).apply()
    }

    private fun dismissedKey(namespace: String) = "dismissed-$namespace"

    private fun cancelAll(arguments: Map<*, *>) {
        workManager.cancelAllWorkByTag(namespaceTag(requireNamespace(arguments)))
    }

    private fun requireNamespace(arguments: Map<*, *>): String {
        val namespace = requireString(arguments, "namespace", 24)
        require(Regex("^[0-9a-f]{24}$").matches(namespace))
        return namespace
    }

    private fun requireString(arguments: Map<*, *>, key: String, max: Int): String {
        val value = arguments[key] as? String ?: throw IllegalArgumentException(key)
        require(value.isNotEmpty() && value.length <= max)
        return value
    }

    companion object {
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/material_downloads"
        private const val PREFERENCES = "material_downloads"
        fun namespaceTag(namespace: String) = "moodle-materials-$namespace"
    }
}
