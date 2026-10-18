package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.TimeUnit

class MaterialDownloadBridge(context: Context) {
    private val workManager = WorkManager.getInstance(context)

    fun handle(method: String, rawArguments: Any?, result: MethodChannel.Result) {
        try {
            val arguments = rawArguments as? Map<*, *> ?: emptyMap<Any, Any>()
            when (method) {
                "enqueue" -> enqueue(MaterialDownloadSpec.from(arguments))
                "cancel" -> cancel(arguments)
                "cancelAll" -> cancelAll(arguments)
                else -> {
                    result.notImplemented()
                    return
                }
            }
            result.success(null)
        } catch (_: IllegalArgumentException) {
            result.error("invalid_material_download", "Dados de download inválidos.", null)
        }
    }

    private fun enqueue(spec: MaterialDownloadSpec) {
        val request = OneTimeWorkRequestBuilder<MaterialDownloadWorker>()
            .setInputData(
                Data.Builder()
                    .putString("id", spec.id)
                    .putString("name", spec.name)
                    .putString("source", spec.source)
                    .putLong("expected_size", spec.expectedSize)
                    .putString("mime_type", spec.mimeType)
                    .putString("namespace", spec.namespace)
                    .build(),
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .addTag(namespaceTag(spec.namespace))
            .build()
        workManager.beginUniqueWork(
            spec.uniqueWorkName,
            ExistingWorkPolicy.KEEP,
            request,
        ).enqueue()
    }

    private fun cancel(arguments: Map<*, *>) {
        val id = requireString(arguments, "id", 512)
        val namespace = requireNamespace(arguments)
        val workName = MaterialDownloadSpec.uniqueWorkName(namespace, id)
        workManager.cancelUniqueWork(workName)
    }

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
        fun namespaceTag(namespace: String) = "moodle-materials-$namespace"
    }
}
