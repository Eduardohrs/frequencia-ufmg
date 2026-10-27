package br.ufmg.frequencia.frequencia_ufmg

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject

class AttendancePermissionsBridge(private val activity: Activity) {
    private val preferences = activity.getSharedPreferences("attendance_permissions", 0)
    private data class Request(val code: Int, val name: String, val result: MethodChannel.Result, val started: Long, val operation: String)
    private var pending: Request? = null

    // A user-started batch may ask once. Per-file enqueue never opens a dialog,
    // and an explicit refusal is revisited only from the permissions screen.
    fun requestDownloadNotificationsIfNeeded(operationId: String? = null) {
        if (!AttendancePermissionPolicy.askForDownloadNotifications(Build.VERSION.SDK_INT,
            granted(Manifest.permission.POST_NOTIFICATIONS), preferences.getBoolean("asked_notifications", false),
            ActivityCompat.shouldShowRequestPermissionRationale(activity, Manifest.permission.POST_NOTIFICATIONS), pending != null)) return
        try {
            request(NOTIFICATION_REQUEST, "notifications", arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                object : MethodChannel.Result {
                    override fun success(result: Any?) {}
                    override fun error(code: String, message: String?, details: Any?) {
                        Log.w(TAG, "notification_prompt_failed code=$code")
                    }
                    override fun notImplemented() {}
                }, operationId?.take(128) ?: "download")
        } catch (error: Exception) {
            pending = null
            Log.w(TAG, "notification_prompt_failed cause=${error.javaClass.simpleName}")
        }
    }

    fun handle(method: String, arguments: Any?, result: MethodChannel.Result) {
        val operation = ((arguments as? Map<*, *>)?.get("operation_id") as? String)?.take(128) ?: "permission"
        try {
            when (method) {
                "read" -> result.success(snapshot(operation))
                "requestLocation" -> request(LOCATION_REQUEST, "location", arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION,
                ), result, operation)
                "requestNotifications" -> {
                    if (Build.VERSION.SDK_INT >= 33) request(NOTIFICATION_REQUEST, "notifications",
                        arrayOf(Manifest.permission.POST_NOTIFICATIONS), result, operation)
                    else { openSettings("notificationSettings"); result.success(null) }
                }
                "locationSettings", "appSettings", "backgroundSettings", "notificationSettings", "batterySettings" -> {
                    openSettings(method)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        } catch (error: Exception) {
            if (pending?.result === result) pending = null
            result.error("attendance_permission_action_failed", "Não foi possível consultar ou ajustar a permissão.",
                mapOf("stage" to "android_permission_action", "action" to method, "operation_id" to operation,
                    "android_sdk" to Build.VERSION.SDK_INT, "cause_type" to error.javaClass.simpleName,
                    "cause_message" to error.message?.take(600)))
        }
    }

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(activity, permission) == PackageManager.PERMISSION_GRANTED

    private fun canRequest(permission: String, name: String) = AttendancePermissionPolicy.requestable(
        granted(permission), preferences.getBoolean("asked_$name", false),
        ActivityCompat.shouldShowRequestPermissionRationale(activity, permission),
    )

    private fun snapshot(operation: String): Map<String, Any> {
        val fine = granted(Manifest.permission.ACCESS_FINE_LOCATION)
        val foreground = fine || granted(Manifest.permission.ACCESS_COARSE_LOCATION)
        val data = mapOf(
            "sdk" to Build.VERSION.SDK_INT,
            "location_services" to LocationManagerCompat.isLocationEnabled(activity.getSystemService(LocationManager::class.java)),
            "foreground_location" to foreground,
            "precise_location" to fine,
            "background_location" to AttendancePermissionPolicy.backgroundGranted(foreground,
                Build.VERSION.SDK_INT, granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)),
            "notifications" to NotificationManagerCompat.from(activity).areNotificationsEnabled(),
            "battery_unrestricted" to activity.getSystemService(PowerManager::class.java)
                .isIgnoringBatteryOptimizations(activity.packageName),
            "location_requestable" to canRequest(Manifest.permission.ACCESS_FINE_LOCATION, "location"),
            "notifications_requestable" to (Build.VERSION.SDK_INT >= 33 &&
                canRequest(Manifest.permission.POST_NOTIFICATIONS, "notifications")),
            "background_option_label" to if (Build.VERSION.SDK_INT >= 30)
                activity.packageManager.backgroundPermissionOptionLabel.toString() else "Permitir o tempo todo",
        )
        Log.i(TAG, JSONObject(data).put("event", "attendance_permission_snapshot").put("operation_id", operation).toString())
        return data
    }

    private fun request(code: Int, name: String, permissions: Array<String>, result: MethodChannel.Result, operation: String) {
        if (pending != null) {
            result.error("attendance_permission_request_busy", "Conclua a permissão que já está aberta.", mapOf("action" to name))
            return
        }
        pending = Request(code, name, result, SystemClock.elapsedRealtime(), operation)
        Log.i(TAG, JSONObject().put("event", "attendance_permission_request_started").put("action", name).put("operation_id", operation).toString())
        ActivityCompat.requestPermissions(activity, permissions, code)
    }

    fun onRequestPermissionsResult(requestCode: Int, grantResults: IntArray) {
        val request = pending ?: return
        if (request.code != requestCode) return
        pending = null
        if (grantResults.isNotEmpty()) preferences.edit().putBoolean("asked_${request.name}", true).apply()
        Log.i(TAG, JSONObject().put("event", "attendance_permission_request_completed")
            .put("action", request.name).put("duration_ms", SystemClock.elapsedRealtime() - request.started)
            .put("operation_id", request.operation)
            .put("granted_count", grantResults.count { it == PackageManager.PERMISSION_GRANTED })
            .put("denied_count", grantResults.count { it != PackageManager.PERMISSION_GRANTED })
            .put("interrupted", grantResults.isEmpty()).toString())
        request.result.success(null)
    }

    private fun openSettings(action: String) {
        val details = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${activity.packageName}"))
        val intent = when (action) {
            "locationSettings" -> Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)
            "notificationSettings" -> if (Build.VERSION.SDK_INT >= 26)
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName) else details
            else -> details // Includes battery: user reviews this app, not a global exclusion list.
        }
        activity.startActivity(intent)
    }

    companion object {
        const val CHANNEL = "br.ufmg.frequencia.frequencia_ufmg/attendance_permissions"
        private const val TAG = "AttendancePermissions"
        private const val LOCATION_REQUEST = 44001
        private const val NOTIFICATION_REQUEST = 44002
    }
}
