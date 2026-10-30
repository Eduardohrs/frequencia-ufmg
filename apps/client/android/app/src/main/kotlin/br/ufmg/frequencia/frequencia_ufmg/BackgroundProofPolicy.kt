package br.ufmg.frequencia.frequencia_ufmg

object BackgroundProofPolicy {
    fun blocked(precise: Boolean, background: Boolean, services: Boolean): String? = when {
        !precise -> "permission_denied"
        !background -> "background_permission_required"
        !services -> "location_disabled"
        else -> null
    }
    fun fix(ageMs: Long, accuracy: Float, recordedDuringRun: Boolean): String? = when {
        ageMs < 0 -> "future_fix"
        ageMs > 120000 -> "stale_fix"
        !recordedDuringRun -> "cached_fix_before_execution"
        !accuracy.isFinite() || accuracy < 0 -> "invalid_accuracy"
        accuracy > 100 -> "inaccurate_fix"
        else -> null
    }
    // PowerManager LOCATION_MODE_* values: 1 GPS-off, 2 all-off, 3 foreground-only.
    fun providers(gps: Boolean, network: Boolean, mode: Int, interactive: Boolean, foreground: Boolean): List<String> {
        if ((mode == 2 && !interactive) || (mode == 3 && !foreground)) return emptyList()
        return buildList {
            if (gps && (mode != 1 || interactive)) add("gps")
            if (network) add("network")
        }
    }
    fun interrupted(status: String, workerPid: Int, currentPid: Int, exitAt: Long, startedAt: Long) =
        status == "running" && workerPid > 0 && workerPid != currentPid && exitAt >= startedAt
    fun canStartForegroundCapture(sdk: Int, unrestricted: Boolean, visible: Boolean) =
        sdk < 31 || unrestricted || visible
    fun proven(status: String, beganInBackground: Boolean, capturedInBackground: Boolean) =
        status == "succeeded" && beganInBackground && capturedInBackground
}

/** Reject cached/imprecise updates without ending the bounded request for a fresh sample. */
class FreshFixWindow(private val startedAtNanos: Long) {
    var sampleCount = 0; private set
    var rejectedCount = 0; private set
    var lastFailure: String? = null; private set
    fun offer(recordedAtNanos: Long, nowNanos: Long, accuracy: Float): Boolean {
        sampleCount++
        lastFailure = BackgroundProofPolicy.fix((nowNanos - recordedAtNanos) / 1000000,
            accuracy, recordedAtNanos >= startedAtNanos)
        if (lastFailure != null) rejectedCount++
        return lastFailure == null
    }
}
