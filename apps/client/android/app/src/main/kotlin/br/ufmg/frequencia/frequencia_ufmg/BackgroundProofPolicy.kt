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
    fun proven(status: String, beganInBackground: Boolean, capturedInBackground: Boolean) =
        status == "succeeded" && beganInBackground && capturedInBackground
}
