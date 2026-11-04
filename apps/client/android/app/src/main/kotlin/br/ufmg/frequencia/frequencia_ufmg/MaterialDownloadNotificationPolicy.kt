package br.ufmg.frequencia.frequencia_ufmg

/** One visible queue, not one notification lifetime per file. */
object MaterialDownloadNotificationPolicy {
    data class Item(val id: String, val name: String, val state: String)
    data class View(val title: String, val text: String, val remaining: Int, val activeId: String?)
    fun view(items: List<Item>, preparing: Int): View? {
        val pending = items.filter { it.state in setOf("running", "enqueued", "blocked") }
        if (pending.isEmpty() && preparing == 0) return null
        val current = pending.firstOrNull { it.state == "running" }
        val text = when {
            current != null -> current.name
            preparing > 0 -> "Preparando arquivos…"
            else -> "Aguardando download"
        }
        return View("Baixando materiais", text, pending.size, current?.id)
    }
}
