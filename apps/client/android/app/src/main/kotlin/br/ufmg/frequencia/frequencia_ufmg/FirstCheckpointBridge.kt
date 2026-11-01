package br.ufmg.frequencia.frequencia_ufmg

import android.content.Context
import androidx.core.content.ContextCompat
import androidx.work.WorkManager
import io.flutter.plugin.common.MethodChannel
import org.json.JSONArray
import org.json.JSONObject

/** Account-scoped, opt-in scheduling. Uses the same capture implementation as the physical proof. */
class FirstCheckpointBridge(private val context: Context) {
    private val prefs get() = context.getSharedPreferences(INDEX, 0)
    private val alarms get() = FirstCheckpointAlarm(context)
    private val work get() = WorkManager.getInstance(context)
    fun handle(method: String, arguments: Any?, result: MethodChannel.Result) = synchronized(LOCK) {
        try {
            val args = arguments as? Map<*, *> ?: emptyMap<Any, Any>()
            if (method == "deactivate") { clear(); result.success(null); return }
            val account = args["account_id"] as? String ?: error("account_required")
            require(account.matches(Regex("[A-Za-z0-9_-]{1,128}"))) { "invalid_account" }
            if (prefs.getString("account_id", null) != account) {
                clear(); check(prefs.edit().putString("account_id", account).commit())
            }
            when (method) {
                "request_alarm_permission" -> {
                    if (android.os.Build.VERSION.SDK_INT >= 31 && !alarms.allowed()) {
                        context.startActivity(android.content.Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                            android.net.Uri.parse("package:" + context.packageName)).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                    }
                    result.success(reports(account))
                }
                "read" -> result.success(reports(account))
                "clear_completed" -> {
                    val stores = prefs.getStringSet("stores", emptySet())!!.toMutableSet()
                    val ended = stores.filter { reconcile(it).optString("status") !in listOf("scheduled", "running") }
                    ended.forEach { key -> stores.remove(key); context.getSharedPreferences(key, 0).edit().clear().commit() }
                    check(prefs.edit().putStringSet("stores", stores).commit())
                    result.success(reports(account))
                }
                "cancel" -> {
                    val id = args["operation_id"] as? String ?: error("operation_required")
                    val key = prefs.getStringSet("stores", emptySet())!!.firstOrNull { key ->
                        load(key).optString("operation_id") == id
                    } ?: error("checkpoint_not_found")
                    val report = load(key)
                    alarms.cancel(key)
                    work.cancelUniqueWork(key)
                    report.put("status", "cancelled").put("first_ping", "indisponivel")
                        .put("updated_at_ms", System.currentTimeMillis())
                    check(context.getSharedPreferences(key, 0).edit().putString("report", report.toString()).commit())
                    BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(report))
                    result.success(reports(account))
                }
                "schedule" -> {
                    val report = JSONObject(args)
                    require(alarms.allowed()) { "exact_alarm_permission_required" }
                    FirstCheckpointPolicy.validate(report, System.currentTimeMillis())
                    val precise = ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED
                    val background = android.os.Build.VERSION.SDK_INT < 29 || ContextCompat.checkSelfPermission(context, android.Manifest.permission.ACCESS_BACKGROUND_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED
                    val locations = context.getSystemService(android.location.LocationManager::class.java)
                    val blocked = BackgroundProofPolicy.blocked(precise, background, androidx.core.location.LocationManagerCompat.isLocationEnabled(locations))
                    require(blocked == null) { blocked ?: "permissions_unavailable" }
                    val power = context.getSystemService(android.os.PowerManager::class.java)
                    require(power.isIgnoringBatteryOptimizations(context.packageName)) { "battery_optimization_required" }

                    val existing = prefs.getStringSet("stores", emptySet())!!.firstOrNull { key ->
                        val r = load(key)
                        r.optString("course_id") == report.getString("course_id") &&
                            r.optString("session_id") == report.getString("session_id") &&
                            r.optLong("starts_at_ms") == report.getLong("starts_at_ms") &&
                            r.optLong("ends_at_ms") == report.getLong("ends_at_ms") &&
                            r.optString("campus_id") == report.getString("campus_id") &&
                            r.optString("status") in listOf("scheduled", "running", "succeeded")
                    }
                    if (existing != null) { result.success(reports(account)); return }
                    val stores = prefs.getStringSet("stores", emptySet())!!.toMutableSet()
                    // Retain evidence; never silently evict an active checkpoint.
                    require(stores.size < 50) { "checkpoint_limit_reached" }
                    val requestId = java.util.UUID.randomUUID().toString()
                    val key = PREFIX + requestId
                    report.put("operation_id", requestId).put("status", "scheduled")
                        .put("first_ping", "indisponivel").put("scheduled_at_ms", System.currentTimeMillis())
                        .put("scheduler", "alarmmanager_exact").put("moment", "first")
                    check(context.getSharedPreferences(key, 0).edit().putString("report", report.toString()).commit())
                    stores.forEach { oldKey ->
                        val old = load(oldKey)
                        if (old.optString("course_id") == report.getString("course_id") &&
                            old.optString("session_id") == report.getString("session_id") &&
                            old.optString("status") in listOf("scheduled", "running")) {
                            alarms.cancel(oldKey)
                            work.cancelUniqueWork(oldKey)
                            old.put("status", "superseded").put("first_ping", "indisponivel")
                            context.getSharedPreferences(oldKey, 0).edit().putString("report", old.toString()).commit()
                        }
                    }
                    stores.add(key); check(prefs.edit().putStringSet("stores", stores).commit())
                    try {
                        alarms.schedule(key, report.getLong("checkpoint_expected_at_ms"))
                        BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(report))
                        result.success(reports(account))
                    } catch (error: Exception) {
                        fail(key, "enqueue_failed", "alarm_schedule", error)
                        result.error("checkpoint_enqueue_failed", "Não foi possível agendar.", FirstCheckpointPolicy.logFields(load(key)).toMap())
                    }
                }
                else -> result.notImplemented()
            }
        } catch (error: Exception) {
            result.error("checkpoint_failed", "Não foi possível concluir a ação do primeiro ping.",
                mapOf("stage" to method, "cause_type" to error.javaClass.simpleName, "cause_message" to error.message?.take(300)))
        }
    }
    private fun load(key: String) = JSONObject(context.getSharedPreferences(key, 0).getString("report", "{}")!!)
    private fun save(key: String, report: JSONObject) {
        check(context.getSharedPreferences(key, 0).edit().putString("report", report.toString()).commit())
        BackgroundLocationProof.emit(FirstCheckpointPolicy.logFields(report))
    }
    fun fail(key: String, status: String, stage: String, error: Exception) = synchronized(LOCK) {
        val report = load(key)
        if (!active(context, report.optString("account_id")) || report.optString("status") !in listOf("scheduled", "running")) return@synchronized
        save(key, report.put("status", status).put("first_ping", "indisponivel")
            .put("stage", stage).put("updated_at_ms", System.currentTimeMillis())
            .put("cause_type", error.javaClass.simpleName).put("cause_message", error.message?.take(300)))
    }
    private fun reconcile(key: String): JSONObject {
        val report = load(key)
        val now = System.currentTimeMillis()
        val failure = FirstCheckpointPolicy.pendingFailure(report, now, alarms.allowed())
        if (failure != null) {
            alarms.cancel(key); work.cancelUniqueWork(key)
            save(key, report.put("status", failure).put("first_ping", "indisponivel")
                .put("stage", "schedule_reconciliation").put("updated_at_ms", now)
                .put("lateness_ms", now - report.getLong("checkpoint_expected_at_ms")))
        } else if (report.optString("status") == "scheduled" && report.optString("scheduler") != "alarmmanager_exact") {
            // Migrate already scheduled checkpoints; never run both schedulers for one operation.
            work.cancelUniqueWork(key)
            try {
                alarms.schedule(key, report.getLong("checkpoint_expected_at_ms"))
                save(key, report.put("scheduler", "alarmmanager_exact").put("stage", "scheduler_migration"))
            } catch (error: Exception) { fail(key, "enqueue_failed", "scheduler_migration", error) }
        }
        return load(key)
    }
    private fun reports(account: String): List<Map<String, Any>> = prefs.getStringSet("stores", emptySet())!!
        .map { reconcile(it) }.filter { it.optString("account_id") == account }
        .map { FirstCheckpointPolicy.logFields(it).toMap() }
    fun dispatch(key: String): JSONObject? = synchronized(LOCK) {
        if (key !in prefs.getStringSet("stores", emptySet())!!) return@synchronized null
        val report = reconcile(key)
        if (!active(context, report.optString("account_id")) || report.optString("status") != "scheduled") return@synchronized null
        save(key, report.put("alarm_received_at_ms", System.currentTimeMillis())
            .put("dispatch_lateness_ms", System.currentTimeMillis() - report.getLong("checkpoint_expected_at_ms"))
            .put("stage", "alarm_dispatch"))
        report
    }
    fun restore(trigger: String) = synchronized(LOCK) {
        prefs.getStringSet("stores", emptySet())!!.forEach { key ->
            val report = reconcile(key)
            if (active(context, report.optString("account_id")) && report.optString("status") == "scheduled") {
                try {
                    alarms.schedule(key, report.getLong("checkpoint_expected_at_ms"))
                    save(key, report.put("stage", "alarm_restore").put("restore_trigger", trigger)
                        .put("restored_at_ms", System.currentTimeMillis()))
                } catch (error: Exception) { fail(key, "enqueue_failed", "alarm_restore", error) }
            }
        }
    }
    private fun clear() {
        // Invalidate ownership before asynchronous cancellation so a running worker cannot save after logout.
        check(prefs.edit().remove("account_id").commit())
        prefs.getStringSet("stores", emptySet())!!.forEach { key ->
            alarms.cancel(key)
            work.cancelUniqueWork(key)
            context.getSharedPreferences(key, 0).edit().clear().commit()
        }
        check(prefs.edit().clear().commit())
    }
    companion object {
        val LOCK = Any()
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/first_checkpoint"
        const val INDEX = "first_checkpoint_index"
        const val PREFIX = "first_checkpoint_"
        fun active(context: Context, account: String): Boolean =
            context.getSharedPreferences(INDEX, 0).getString("account_id", null) == account
        private fun JSONObject.toMap(): Map<String, Any> = keys().asSequence().associateWith { get(it) }
    }
}
