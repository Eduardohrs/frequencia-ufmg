package br.ufmg.frequencia.frequencia_ufmg

import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private var attendancePermissions: AttendancePermissionsBridge? = null
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        attendancePermissions = AttendancePermissionsBridge(this)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, AttendancePermissionsBridge.CHANNEL)
            .setMethodCallHandler { call, result -> attendancePermissions!!.handle(call.method, call.arguments, result) }
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

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        attendancePermissions?.onRequestPermissionsResult(requestCode, grantResults)
    }

}
