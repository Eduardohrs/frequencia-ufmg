package br.ufmg.frequencia.frequencia_ufmg

import android.content.Intent
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.EventChannel

class MainActivity: FlutterActivity() {
    private var deliveryEvents: CheckpointDeliveryEvents? = null
    private var attendancePermissions: AttendancePermissionsBridge? = null
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        acceptCheckpointNotice(intent)
        deliveryEvents = CheckpointDeliveryEvents(applicationContext)
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, CheckpointDeliveryEvents.CHANNEL).setStreamHandler(deliveryEvents)
        attendancePermissions = AttendancePermissionsBridge(this)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, AttendancePermissionsBridge.CHANNEL)
            .setMethodCallHandler { call, result -> attendancePermissions!!.handle(call.method, call.arguments, result) }
        val checkpoint = FirstCheckpointBridge(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, FirstCheckpointBridge.CHANNEL)
            .setMethodCallHandler { call, result -> checkpoint.handle(call.method, call.arguments, result) }
        val proof = BackgroundLocationProof(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, BackgroundLocationProof.CHANNEL)
            .setMethodCallHandler { call, result -> proof.handle(call.method, result) }
        val bridge = MaterialDownloadBridge(applicationContext)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            MaterialDownloadBridge.CHANNEL,
        ).setMethodCallHandler { call, result ->
            if (call.method == "beginPreparation") attendancePermissions?.requestDownloadNotificationsIfNeeded(
                (call.arguments as? Map<*, *>)?.get("operation_id") as? String,
            )
            bridge.handle(call.method, call.arguments, result)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        acceptCheckpointNotice(intent)
    }
    private fun acceptCheckpointNotice(intent:Intent?) {
        try { CheckpointNotifications.opened(applicationContext,intent) }
        catch(error:Exception) { BackgroundLocationProof.emit(org.json.JSONObject().put("event","checkpoint_notification_open_failed").put("failure",CheckpointDeliveryPolicy.failureDetails(error))) }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        deliveryEvents?.dispose(); deliveryEvents = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        attendancePermissions?.onRequestPermissionsResult(requestCode, grantResults)
    }

}
