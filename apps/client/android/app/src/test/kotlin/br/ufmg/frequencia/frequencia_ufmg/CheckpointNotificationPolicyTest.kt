package br.ufmg.frequencia.frequencia_ufmg
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
class CheckpointNotificationPolicyTest {
    private fun report(status:String="succeeded",outcome:String="",attendance:String="")=JSONObject()
        .put("account_id","owner").put("operation_id","operation").put("status",status)
        .put("delivery_status",outcome).put("delivery_attendance_status",attendance)
    @Test fun noticesFollowCanonicalOutcomeAndDoNotGuessAttendance() {
        for(status in listOf("presente","pendente","")) assertNull(CheckpointNotificationPolicy.select("owner",listOf(report(outcome="applied",attendance=status))))
        for(status in listOf("ausente","chegou_atrasado","saiu_mais_cedo")) {
            val notice=CheckpointNotificationPolicy.select("owner",listOf(report(outcome="applied",attendance=status)))!!
            assertEquals("review",notice.kind)
        }
        for(status in listOf("preserved","discarded")) assertNull(CheckpointNotificationPolicy.select("owner",listOf(report("location_timeout",status))))
        assertEquals("manual",CheckpointNotificationPolicy.select("owner",listOf(report(outcome="unresolved")))!!.kind)
        assertEquals("manual",CheckpointNotificationPolicy.select("owner",listOf(report(outcome="rejected")))!!.kind)
        assertEquals("upload",CheckpointNotificationPolicy.select("owner",listOf(report(outcome="retry")))!!.kind)
        assertEquals("capture",CheckpointNotificationPolicy.select("owner",listOf(report("checkpoint_outside_window")))!!.kind)
        for(status in listOf("scheduled","running","succeeded","cancelled","superseded")) assertNull(CheckpointNotificationPolicy.select("owner",listOf(report(status))))
    }
    @Test fun aggregationIsStablePrivateAndScopedToAccount() {
        val a=report("location_timeout").put("course_code","SECRET_COURSE")
        val b=report(outcome="retry").put("operation_id","other")
        val foreign=report("failed").put("account_id","foreign")
        val n=CheckpointNotificationPolicy.select("owner",listOf(a,b,foreign))!!
        assertEquals(n.fingerprint,CheckpointNotificationPolicy.select("owner",listOf(b,a))!!.fingerprint)
        b.put("delivery_attempt",99)
        assertEquals(n.fingerprint,CheckpointNotificationPolicy.select("owner",listOf(a,b))!!.fingerprint)
        assertEquals(2,n.operations.size);assertFalse(n.body.contains("SECRET_COURSE"));assertFalse(n.body.contains("owner"))
        assertNull(CheckpointNotificationPolicy.select("different",listOf(a,b)))
        assertNull(CheckpointNotificationPolicy.select("owner",listOf(a),setOf("operation")))
        assertNotEquals(n.fingerprint,CheckpointNotificationPolicy.select("owner",listOf(a))!!.fingerprint)
    }
    @Test fun notificationPermissionChannelAndDedupDecisionsAreExplicit() {
        assertEquals("clear",CheckpointNotificationPolicy.decision(null,"old","posted",true,true))
        assertEquals("blocked_permission",CheckpointNotificationPolicy.decision("new","old","posted",false,true))
        assertEquals("blocked_channel",CheckpointNotificationPolicy.decision("new","old","posted",true,false))
        assertEquals("unchanged",CheckpointNotificationPolicy.decision("same","same","posted",true,true))
        assertEquals("post",CheckpointNotificationPolicy.decision("same","same","blocked_permission",true,true))
    }
    @Test fun notificationOpenRejectsForeignAndRepeatedTokens() {
        assertTrue(CheckpointNotificationPolicy.canOpen("owner","owner","new","old"))
        assertFalse(CheckpointNotificationPolicy.canOpen("owner","different","new","old"))
        assertFalse(CheckpointNotificationPolicy.canOpen(null,"owner","new","old"))
        assertFalse(CheckpointNotificationPolicy.canOpen("owner","owner","","old"))
        assertFalse(CheckpointNotificationPolicy.canOpen("owner","owner","same","same"))
        assertFalse(CheckpointNotificationPolicy.canOpen("owner","owner","x".repeat(129),"old"))
    }
}
