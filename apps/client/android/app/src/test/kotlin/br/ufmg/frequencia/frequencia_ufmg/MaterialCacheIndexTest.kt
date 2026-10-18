package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class MaterialCacheIndexTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun `records only durable metadata and replaces the same logical file`() {
        val directory = temporaryFolder.newFolder("cache")
        val first = spec(name = "Plano.pdf")
        val replacement = spec(name = "Plano atualizado.pdf")

        MaterialCacheIndex.record(directory, first, 11)
        MaterialCacheIndex.record(directory, replacement, 19)

        val raw = directory.resolve("index.json").readText()
        val root = JSONObject(raw)
        val files = root.getJSONArray("files")
        assertEquals(1, root.getInt("version"))
        assertEquals(1, files.length())
        assertEquals("Plano atualizado.pdf", files.getJSONObject(0).getString("name"))
        assertEquals(19, files.getJSONObject(0).getLong("size"))
        assertFalse(raw.contains("tokenpluginfile"))
        assertFalse(raw.contains("aaaaaaaaaaaaaaaa"))
    }

    private fun spec(name: String) = MaterialDownloadSpec.from(
        mapOf(
            "id" to "2026-2/3701/102/Plano.pdf",
            "name" to name,
            "source" to (
                "https://virtual.ufmg.br/20262/tokenpluginfile.php/" +
                    "aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf" +
                    "?forcedownload=1"
            ),
            "expected_size" to 11L,
            "mime_type" to "application/pdf",
            "namespace" to "0123456789abcdef01234567",
        ),
    )
}
