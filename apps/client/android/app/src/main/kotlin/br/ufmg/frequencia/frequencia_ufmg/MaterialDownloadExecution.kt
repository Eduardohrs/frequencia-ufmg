package br.ufmg.frequencia.frequencia_ufmg

/** Keep scheduling and notification delivery on the same platform boundary. */
internal object MaterialDownloadExecution {
    fun queuedAt(tags: Set<String>): Long = tags.filter {
        it.startsWith("material-queued-at-")
    }.mapNotNull {
        it.removePrefix("material-queued-at-").toLongOrNull()
    }.maxOrNull() ?: 0L

    fun usesScheduledJob(sdk: Int): Boolean = sdk >= 31

    fun updateNotification(
        sdk: Int,
        notify: () -> Unit,
        startForeground: () -> Unit,
        notificationDenied: (SecurityException) -> Unit,
    ) {
        if (usesScheduledJob(sdk)) {
            try {
                notify()
            } catch (error: SecurityException) {
                // Notification permission is optional; JobScheduler owns execution.
                notificationDenied(error)
            }
        } else {
            startForeground()
        }
    }
}
