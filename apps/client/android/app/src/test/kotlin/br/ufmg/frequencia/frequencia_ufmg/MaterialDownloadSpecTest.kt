package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class MaterialDownloadSpecTest {
    @Test
    fun `truncated bodies are never complete but unknown or decoded lengths are not guessed`() {
        assertFalse(MaterialDownloadSpec.isCompleteBody(100, 99, null))
        assertFalse(MaterialDownloadSpec.isCompleteBody(100, 101, "identity"))
        assertFalse(MaterialDownloadSpec.isCompleteBody(-1, -1, null))
        assertTrue(MaterialDownloadSpec.isCompleteBody(100, 100, null))
        assertTrue(MaterialDownloadSpec.isCompleteBody(-1, 42, null))
        assertTrue(MaterialDownloadSpec.isCompleteBody(0, 0, ""))
        assertTrue(MaterialDownloadSpec.isCompleteBody(10, 100, "gzip"))
    }
    private val valid = mapOf<String, Any>(
        "id" to "2026-2/3701/102/Plano.pdf",
        "name" to "Plano.pdf",
        "source" to (
            "https://virtual.ufmg.br/20262/tokenpluginfile.php/" +
                "aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf" +
                "?forcedownload=1"
        ),
        "expected_size" to 11L,
        "mime_type" to "application/pdf",
        "namespace" to "0123456789abcdef01234567",
    )

    @Test
    fun `validates and derives opaque local identifiers`() {
        val spec = MaterialDownloadSpec.from(valid)

        assertEquals("Plano.pdf", spec.name)
        assertEquals("f2d729c4f101bc5d.pdf", spec.storedName)
        assertFalse(spec.uniqueWorkName.contains("Plano"))
        assertFalse(spec.uniqueWorkName.contains("3701"))
    }

    @Test
    fun `serializes one user queue behind one notification`() {
        val first = MaterialDownloadSpec.from(valid)
        val second = MaterialDownloadSpec.from(
            valid.toMutableMap().apply {
                this["id"] = "2026-2/3701/103/Outro.pdf"
                this["name"] = "Outro.pdf"
            },
        )

        assertEquals(first.queueWorkName, second.queueWorkName)
        assertEquals(first.notificationId, second.notificationId)
        assertFalse(first.itemTag == second.itemTag)
    }

    @Test
    fun `predecessor output cannot rename or replace the next download`() {
        val requested = MaterialDownloadSpec.from(valid)
        val merged = requested.workerInput() + mapOf(
            "id" to "previous-file",
            "name" to "Previous.pdf",
            "downloaded" to 309319L,
            "failure_code" to "timeout",
        )
        val actual = MaterialDownloadSpec.fromWorkerInput(merged)
        assertEquals(requested.id, actual.id)
        assertEquals(requested.name, actual.name)
        assertEquals(requested.source, actual.source)
        assertEquals(requested.expectedSize, actual.expectedSize)
        assertEquals(requested.mimeType, actual.mimeType)
        assertEquals(requested.namespace, actual.namespace)
        assertEquals(requested.id, MaterialDownloadSpec.fromWorkerInput(valid).id)
    }

    @Test
    fun `rejects downloads outside the Moodle direct contract`() {
        val invalid = valid.toMutableMap().apply {
            this["source"] = "https://example.com/private.pdf"
        }

        assertThrows(IllegalArgumentException::class.java) {
            MaterialDownloadSpec.from(invalid)
        }
    }

    @Test
    fun `rejects unsafe namespaces and oversized files`() {
        for (invalid in listOf(
            valid.toMutableMap().apply { this["namespace"] = "../escape" },
            valid.toMutableMap().apply { this["expected_size"] = 104_857_601L },
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                MaterialDownloadSpec.from(invalid)
            }
        }
    }

    @Test
    fun `rejects payloads too large for the persistent queue`() {
        val invalid = valid.toMutableMap().apply {
            this["source"] = "https://virtual.ufmg.br/" + "a".repeat(4097)
        }

        assertThrows(IllegalArgumentException::class.java) {
            MaterialDownloadSpec.from(invalid)
        }
    }
}
