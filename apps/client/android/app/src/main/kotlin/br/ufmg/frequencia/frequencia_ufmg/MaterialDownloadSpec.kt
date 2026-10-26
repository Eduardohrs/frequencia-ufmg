package br.ufmg.frequencia.frequencia_ufmg

import java.net.URI
import java.security.MessageDigest

data class MaterialDownloadSpec(
    val id: String,
    val name: String,
    val source: String,
    val expectedSize: Long,
    val mimeType: String,
    val namespace: String,
) {
    val storedName: String = sha256(id).take(16) + safeExtension(name)
    val uniqueWorkName: String = uniqueWorkName(namespace, id)
    val queueWorkName: String = "moodle-material-queue-$namespace"
    val itemTag: String = uniqueWorkName
    val notificationId: Int = sha256(namespace).take(7).toInt(16)

    // Prerequisite output is merged into the next WorkManager request.
    // Keep immutable request fields distinct from reported progress/output.
    fun workerInput(): Map<String, Any> = mapOf(
        "request_id" to id,
        "request_name" to name,
        "request_source" to source,
        "request_expected_size" to expectedSize,
        "request_mime_type" to mimeType,
        "request_namespace" to namespace,
    )

    companion object {
        const val MAX_FILE_BYTES = 100L * 1024L * 1024L

        fun fromWorkerInput(input: Map<*, *>): MaterialDownloadSpec = from(
            REQUIRED_KEYS.associateWith { key -> input["request_$key"] ?: input[key] },
        )

        fun isCompleteBody(declared: Long, received: Long, encoding: String?): Boolean =
            received >= 0 && (
                declared < 0 ||
                    (!encoding.isNullOrEmpty() && encoding != "identity") ||
                    declared == received
                )

        fun uniqueWorkName(namespace: String, id: String): String =
            "moodle-material-" + sha256("$namespace/$id").take(24)

        fun from(arguments: Map<*, *>): MaterialDownloadSpec {
            require(arguments.keys == REQUIRED_KEYS)
            val id = arguments["id"] as? String ?: throw IllegalArgumentException("id")
            val name = arguments["name"] as? String ?: throw IllegalArgumentException("name")
            val source = arguments["source"] as? String ?: throw IllegalArgumentException("source")
            val expectedSize = (arguments["expected_size"] as? Number)?.toLong()
                ?: throw IllegalArgumentException("expected_size")
            val mimeType = arguments["mime_type"] as? String
                ?: throw IllegalArgumentException("mime_type")
            val namespace = arguments["namespace"] as? String
                ?: throw IllegalArgumentException("namespace")
            require(id.isNotEmpty() && id.length <= 512)
            require(name.isNotBlank() && name == name.trim() && name.length <= 255)
            require(name.none { it.isISOControl() })
            require(source.length <= 4096)
            require(expectedSize in 0..MAX_FILE_BYTES)
            require(MIME_TYPE.matches(mimeType))
            require(NAMESPACE.matches(namespace))
            require(isSafeMoodleUrl(source))
            return MaterialDownloadSpec(id, name, source, expectedSize, mimeType, namespace)
        }

        private val REQUIRED_KEYS = setOf(
            "id",
            "name",
            "source",
            "expected_size",
            "mime_type",
            "namespace",
        )
        private val MIME_TYPE = Regex("^[a-z0-9.+-]+/[a-z0-9.+-]+$")
        private val NAMESPACE = Regex("^[0-9a-f]{24}$")
        private val PERIOD = Regex("^[0-9]{5}$")
        private val TOKEN = Regex("^[A-Za-z0-9]{16,256}$")
        private val EXTENSION = Regex("^\\.[A-Za-z0-9]{1,10}$")

        private fun isSafeMoodleUrl(value: String): Boolean = try {
            val uri = URI(value)
            val segments = uri.path.split('/').filter { it.isNotEmpty() }
            uri.scheme == "https" &&
                uri.host == "virtual.ufmg.br" &&
                uri.port == -1 &&
                uri.userInfo == null &&
                uri.fragment == null &&
                uri.rawQuery == "forcedownload=1" &&
                segments.size >= 8 &&
                PERIOD.matches(segments[0]) &&
                segments[1] == "tokenpluginfile.php" &&
                TOKEN.matches(segments[2]) &&
                segments.drop(3).none { it.isEmpty() || it == "." || it == ".." || '\\' in it }
        } catch (_: Exception) {
            false
        }

        private fun safeExtension(name: String): String {
            val dot = name.lastIndexOf('.')
            if (dot <= 0 || dot == name.lastIndex) return ""
            val extension = name.substring(dot)
            return if (EXTENSION.matches(extension)) extension else ""
        }

        private fun sha256(value: String): String = MessageDigest
            .getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}
