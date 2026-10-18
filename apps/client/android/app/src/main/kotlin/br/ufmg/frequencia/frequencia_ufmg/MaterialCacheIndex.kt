package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object MaterialCacheIndex {
    private val lock = Any()

    fun record(directory: File, spec: MaterialDownloadSpec, actualSize: Long) = synchronized(lock) {
        val index = File(directory, "index.json")
        val root = if (index.exists()) JSONObject(index.readText()) else JSONObject()
        val current = root.optJSONArray("files") ?: JSONArray()
        val next = JSONArray()
        for (position in 0 until current.length()) {
            val entry = current.getJSONObject(position)
            if (entry.optString("id") != spec.id) next.put(entry)
        }
        next.put(
            JSONObject()
                .put("id", spec.id)
                .put("name", spec.name)
                .put("size", actualSize)
                .put("mime_type", spec.mimeType)
                .put("stored_name", spec.storedName),
        )
        val updated = JSONObject().put("version", 1).put("files", next)
        val temporary = File(directory, "index.json.part")
        temporary.writeText(updated.toString())
        if (!temporary.renameTo(index)) {
            temporary.copyTo(index, overwrite = true)
            temporary.delete()
        }
    }
}
