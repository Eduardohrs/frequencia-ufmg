package br.ufmg.frequencia.frequencia_ufmg

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.Observer
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.util.UUID
import org.json.JSONObject

/** Observes durable WorkManager states, including completion after doWork returns. */
object MaterialDownloadNotifications {
    private const val CHANNEL = "material_downloads"
    private const val UPDATE_INTERVAL_MS = 750L
    private val handler = Handler(Looper.getMainLooper())
    private val queues = mutableMapOf<String, Queue>()
    private class Queue(val context: Context, val namespace: String) {
        val source = WorkManager.getInstance(context).getWorkInfosByTagLiveData(MaterialDownloadBridge.namespaceTag(namespace))
        lateinit var observer: Observer<List<WorkInfo>>
        var lastView: MaterialDownloadNotificationPolicy.View? = null
        var lastPosted = 0L
        var deferred: Runnable? = null
        var denialLogged = false
        var revision = 0L
    }
    fun id(namespace: String): Int = MaterialDownloadSpec.notificationId(namespace)
    fun preparation(context: Context): Notification = builder(context)
        .setContentTitle("Baixando materiais").setContentText("Preparando arquivos…")
        .setProgress(0, 0, true).build()
    fun refresh(context: Context, namespace: String) {
        handler.post {
            try {
                val queue = queues[namespace] ?: Queue(context.applicationContext, namespace).also { q ->
                    queues[namespace] = q
                    q.observer = Observer { render(q, it) }
                    q.source.observeForever(q.observer)
                }
                queue.source.value?.let { render(queue, it) }
            } catch (error: Exception) { log(namespace, "queue_observation_failed", error) }
        }
    }
    private fun render(queue: Queue, work: List<WorkInfo>, confirmedEmpty: Boolean = false) {
        if (queues[queue.namespace] !== queue) return
        val view = MaterialDownloadNotificationPolicy.view(work.map { info ->
            MaterialDownloadNotificationPolicy.Item(info.id.toString(), info.progress.getString("name")
                ?: info.tags.firstOrNull { it.startsWith("material-name-") }?.removePrefix("material-name-") ?: "Material",
                info.state.name.lowercase())
        }, MaterialPreparationService.pendingCount(queue.namespace))
        if (view == null) {
            if (!confirmedEmpty) {
                // LiveData can still hold the empty snapshot from before enqueue.
                // Confirm against the committed queue before removing the handover notification.
                val revision = queue.revision
                val fresh = WorkManager.getInstance(queue.context)
                    .getWorkInfosByTag(MaterialDownloadBridge.namespaceTag(queue.namespace))
                fresh.addListener({
                    try {
                        if (queue.revision == revision) render(queue, fresh.get(), true)
                    } catch (error: Exception) { log(queue.namespace, "queue_confirmation_failed", error) }
                }, androidx.core.content.ContextCompat.getMainExecutor(queue.context))
                return
            }
            queue.deferred?.let(handler::removeCallbacks)
            queue.source.removeObserver(queue.observer)
            queues.remove(queue.namespace)
            queue.context.getSystemService(NotificationManager::class.java).cancel(id(queue.namespace))
            log(queue.namespace, "queue_finished")
            return
        }
        queue.revision++
        if (view == queue.lastView) return
        val now = SystemClock.elapsedRealtime()
        val wait = UPDATE_INTERVAL_MS - (now - queue.lastPosted)
        if (wait > 0 && queue.lastView != null) {
            if (queue.deferred == null) {
                queue.deferred = Runnable { queue.deferred = null; queue.source.value?.let { render(queue, it) } }
                handler.postDelayed(queue.deferred!!, wait)
            }
            return
        }
        val notification = builder(queue.context).setContentTitle(view.title)
            .setContentText(view.text).setSubText(if (view.remaining > 0) "${view.remaining} na fila" else null)
            .setProgress(0,0,true)
            .setContentIntent(PendingIntent.getActivity(queue.context, id(queue.namespace),
                Intent(queue.context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        view.activeId?.let { notification.addAction(android.R.drawable.ic_menu_close_clear_cancel,
            "Cancelar arquivo", WorkManager.getInstance(queue.context).createCancelPendingIntent(UUID.fromString(it))) }
        try {
            queue.context.getSystemService(NotificationManager::class.java).notify(id(queue.namespace), notification.build())
            if (queue.lastView == null) log(queue.namespace, "queue_started")
            queue.lastView = view; queue.lastPosted = now
        } catch (error: SecurityException) {
            if (!queue.denialLogged) {
                log(queue.namespace, "notification_denied", error)
                queue.denialLogged = true
            }
        }
    }
    private fun builder(context: Context): NotificationCompat.Builder {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel(CHANNEL,"Downloads de materiais",NotificationManager.IMPORTANCE_LOW))
        return NotificationCompat.Builder(context,CHANNEL).setSmallIcon(context.applicationInfo.icon)
            .setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
    }
    private fun log(namespace: String, stage: String, error: Throwable? = null) {
        Log.i("MaterialDownload",JSONObject().put("event","material_download_notification")
            .put("stage",stage).put("namespace",namespace).put("notification_id",id(namespace))
            .put("error_type",error?.javaClass?.simpleName).toString())
    }
}
