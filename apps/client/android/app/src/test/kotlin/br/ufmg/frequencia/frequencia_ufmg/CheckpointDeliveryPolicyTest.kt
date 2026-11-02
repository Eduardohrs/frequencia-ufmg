package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CheckpointDeliveryPolicyTest {
    private val start=1800000000000L
    private fun report(moment: String, status: String="succeeded")=JSONObject()
        .put("account_id","u").put("course_id","c").put("session_id","s")
        .put("starts_at_ms",start).put("ends_at_ms",start+3000000L).put("campus_id","pampulha")
        .put("lesson_count",1).put("call_count",1).put("moment",moment)
        .put("operation_id",moment+"-id").put("status",status).put("scheduled_at_ms",start)
        .put("checkpoint_expected_at_ms",start+if(moment=="first")1200000L else 1800000L)
        .put("captured_at_ms",start+if(moment=="first")1200100L else 1800100L)
        .put(if(moment=="first")"first_ping" else "second_ping","fora").put("delivery_enabled",true)

    @Test fun completedReportCrossesRealFlutterCodecWithNestedTimingsAndNulls() {
        val source=report("first").put("delivery_status","applied")
            .put("delivery_timings",JSONObject().put("identity_ms",1).put("http_ms",1382)
                .put("optional",JSONObject.NULL).put("steps",org.json.JSONArray().put("identity").put(JSONObject().put("ok",true))))
        val fields=FirstCheckpointPolicy.logFields(source)
        val channel=FirstCheckpointPolicy.channelFields(fields)
        val encoded=io.flutter.plugin.common.StandardMessageCodec.INSTANCE.encodeMessage(channel)!!
        encoded.flip()
        val decoded=io.flutter.plugin.common.StandardMessageCodec.INSTANCE.decodeMessage(encoded) as Map<*,*>
        val timings=decoded["delivery_timings"] as Map<*,*>
        assertEquals(1382,timings["http_ms"])
        assertNull(timings["optional"])
        assertEquals(listOf("identity",mapOf("ok" to true)),timings["steps"])
        assertEquals("applied",decoded["delivery_status"])
    }
    @Test fun pairsMostRecentMomentsWithoutMixingRevisionsOrAccounts() {
        val a=report("first");val b=report("second")
        val canceled=report("first","cancelled").put("scheduled_at_ms",start+1)
        val unrelated=report("second").put("account_id","other").put("scheduled_at_ms",start+2)
        val body=CheckpointDeliveryPolicy.payload(a,listOf(a,b,canceled,unrelated))
        assertEquals("cancelled",body.getJSONObject("first").getString("status"))
        assertEquals("second-id",body.getJSONObject("second").getString("operation_id"))
        assertEquals(1,body.getInt("lesson_count"))
        val wrongConfig=report("second").put("call_count",2).put("operation_id","wrong").put("scheduled_at_ms",start+100)
        assertEquals("second-id",CheckpointDeliveryPolicy.payload(a,listOf(a,b,wrongConfig)).getJSONObject("second").getString("operation_id"))
        assertFalse(body.toString().contains("rectangles"))
        assertEquals(CheckpointDeliveryPolicy.workName(a),CheckpointDeliveryPolicy.workName(b))
        assertNotEquals(CheckpointDeliveryPolicy.workName(a),CheckpointDeliveryPolicy.workName(unrelated))
    }
    @Test fun missingMomentsWaitForTheirWindowButCompletePairIsReadyImmediately() {
        val a=report("first");val b=report("second")
        assertEquals(start+2100001L,CheckpointDeliveryPolicy.readyAt(a,listOf(a),start))
        assertEquals(start,CheckpointDeliveryPolicy.readyAt(a,listOf(a,b),start))
        assertTrue(CheckpointDeliveryPolicy.payload(a,listOf(a)).isNull("second"))
        assertEquals(start+1500001L,CheckpointDeliveryPolicy.readyAt(a,listOf(report("first","scheduled"),b),start))
    }
    @Test fun deliveryOutcomesAreExplicitAndOnlyConfirmedTerminalResultsCanBeCleared() {
        val a=report("first").put("status","succeeded")
        assertFalse(CheckpointDeliveryPolicy.acknowledged(a))
        for(status in listOf("applied","already_applied","preserved","unresolved","discarded","rejected")) {
            a.put("delivery_status",status)
            assertTrue(CheckpointDeliveryPolicy.acknowledged(a))
        }
        assertEquals("retry",CheckpointDeliveryPolicy.httpOutcome(503,JSONObject()))
        assertEquals("discarded",CheckpointDeliveryPolicy.httpOutcome(404,JSONObject().put("error","session_not_found")))
        assertEquals("retry",CheckpointDeliveryPolicy.httpOutcome(404,JSONObject().put("error","not_found")))
        assertEquals("rejected",CheckpointDeliveryPolicy.httpOutcome(400,JSONObject().put("error","checkpoint_rejected")))
        assertEquals("retry",CheckpointDeliveryPolicy.httpOutcome(200,JSONObject().put("outcome","waiting")))
        assertEquals("applied",CheckpointDeliveryPolicy.httpOutcome(200,JSONObject().put("outcome","applied")))
        assertEquals("retry",CheckpointDeliveryPolicy.httpOutcome(200,JSONObject().put("outcome","unknown")))
    }
    @Test fun aResponseMustConfirmTheSameOperationsBeforeAcknowledgement() {
        val body=CheckpointDeliveryPolicy.payload(report("first"),listOf(report("first"),report("second")))
        val response=JSONObject().put("outcome","applied").put("first_operation_id","first-id").put("second_operation_id","second-id")
        assertEquals("applied",CheckpointDeliveryPolicy.confirmedOutcome(200,response,body))
        response.put("second_operation_id","other")
        assertEquals("retry",CheckpointDeliveryPolicy.confirmedOutcome(200,response,body))
        assertEquals("retry",CheckpointDeliveryPolicy.confirmedOutcome(503,response,body))
    }
    @Test fun queuedEvidenceCannotBeClearedBeforeServerConfirmation() {
        val a=report("first");val b=report("second")
        assertFalse(FirstCheckpointPolicy.canClear(a,listOf(a,b),start+4000000L))
        a.put("delivery_status","applied")
        assertFalse(FirstCheckpointPolicy.canClear(a,listOf(a,b),start+4000000L))
        b.put("delivery_status","applied")
        assertTrue(FirstCheckpointPolicy.canClear(a,listOf(a,b),start+4000000L))
    }
    @Test fun failuresKeepRootCauseAndReadableContextButNeverCredentials() {
        val error=RuntimeException("wrapper",IllegalStateException("connection timeout for c/s; Bearer secret-value token=hidden eyJhbGciOiJIUzI1NiJ9.payload.signature"))
        val details=CheckpointDeliveryPolicy.failureDetails(error)
        assertEquals("IllegalStateException",details.getString("root_cause_type"))
        assertTrue(details.getString("root_cause_message").contains("connection timeout for c/s"))
        assertFalse(details.toString().contains("secret-value"))
        assertFalse(details.toString().contains("hidden"))
        assertFalse(details.toString().contains("eyJhbGci"))
    }
    @Test fun aPartialLocalAcknowledgementMustNotStopTheRemainingOutbox() {
        val a=report("first").put("delivery_status","applied");val b=report("second")
        assertFalse(CheckpointDeliveryPolicy.allAcknowledged(a,listOf(a,b)))
        b.put("delivery_status","applied")
        assertTrue(CheckpointDeliveryPolicy.allAcknowledged(a,listOf(a,b)))
    }
}
