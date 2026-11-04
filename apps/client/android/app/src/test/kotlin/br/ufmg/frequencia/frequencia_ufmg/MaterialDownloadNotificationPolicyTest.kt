package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.*
import org.junit.Test

class MaterialDownloadNotificationPolicyTest {
    private fun file(id: String, state: String) = MaterialDownloadNotificationPolicy.Item(id,"Arquivo $id.pdf",state)
    @Test fun `one queue stays visible between consecutive files`() {
        val first=MaterialDownloadNotificationPolicy.view(listOf(file("a","running"),file("b","blocked")),0)!!
        val between=MaterialDownloadNotificationPolicy.view(listOf(file("a","succeeded"),file("b","enqueued")),0)!!
        val second=MaterialDownloadNotificationPolicy.view(listOf(file("a","succeeded"),file("b","running")),0)!!
        assertEquals("Baixando materiais",first.title);assertEquals(first.title,between.title);assertEquals(first.title,second.title)
        assertEquals(2,first.remaining);assertEquals(1,between.remaining);assertEquals("b",second.activeId)
        assertNull(MaterialDownloadNotificationPolicy.view(listOf(file("a","succeeded"),file("b","succeeded")),0))
    }
    @Test fun `preparation and download share a continuous queue lifetime`() {
        assertNotNull(MaterialDownloadNotificationPolicy.view(emptyList(),5))
        assertEquals("Preparando arquivos…",MaterialDownloadNotificationPolicy.view(emptyList(),5)!!.text)
        assertNotNull(MaterialDownloadNotificationPolicy.view(listOf(file("a","succeeded")),3))
        assertEquals("Arquivo b.pdf",MaterialDownloadNotificationPolicy.view(listOf(file("b","running")),3)!!.text)
        assertNull(MaterialDownloadNotificationPolicy.view(emptyList(),0))
    }
    @Test fun `retry and offline wait remain visible without success claims`() {
        val view=MaterialDownloadNotificationPolicy.view(listOf(file("a","enqueued")),0)!!
        assertNull(view.activeId);assertEquals("Aguardando download",view.text)
        assertEquals(1,view.remaining)
    }
    @Test fun `failure and cancellation do not hide remaining work or leave an orphan notification`() {
        assertNotNull(MaterialDownloadNotificationPolicy.view(listOf(file("a","failed"),file("b","blocked")),0))
        assertNull(MaterialDownloadNotificationPolicy.view(listOf(file("a","cancelled"),file("b","failed")),0))
    }
    @Test fun `queue identities do not change between preparation and file workers`() {
        val namespace="a".repeat(24)
        val a=MaterialDownloadSpec("a","A.pdf","https://virtual.ufmg.br/a",10,"application/pdf",namespace)
        val b=MaterialDownloadSpec("b","B.pdf","https://virtual.ufmg.br/b",20,"application/pdf",namespace)
        assertEquals(a.notificationId,b.notificationId)
        assertEquals(MaterialDownloadSpec.notificationId(namespace),a.notificationId)
        assertNotEquals(MaterialDownloadSpec.notificationId(namespace),MaterialDownloadSpec.notificationId("b".repeat(24)))
    }
}
