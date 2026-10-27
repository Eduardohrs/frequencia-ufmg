package br.ufmg.frequencia.frequencia_ufmg

internal object AttendancePermissionPolicy {
    fun askForDownloadNotifications(sdk: Int, granted: Boolean, askedBefore: Boolean,
        rationale: Boolean, pending: Boolean): Boolean =
        sdk >= 33 && !granted && !askedBefore && !rationale && !pending

    fun requestable(granted: Boolean, askedBefore: Boolean, rationale: Boolean): Boolean =
        !granted && (!askedBefore || rationale)

    fun backgroundGranted(foreground: Boolean, sdk: Int, background: Boolean): Boolean =
        foreground && (sdk < 29 || background)
}
