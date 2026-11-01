package br.ufmg.frequencia.frequencia_ufmg
import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import org.json.JSONArray

class FirstCheckpointPolicyTest {
    private val now = 2000000000000L
    private fun report() = JSONObject().put("account_id", "owner").put("course_id", "poo")
        .put("session_id", "session-1").put("campus_id", "pampulha")
        .put("starts_at_ms", now).put("ends_at_ms", now + 6000000)
        .put("rectangles", JSONArray().put(JSONObject().put("south", -20.0).put("north", -19.0)
            .put("west", -44.0).put("east", -43.0)))
    @Test fun scheduleUsesStartPlusTwentyMinutes() {
        val r = report(); FirstCheckpointPolicy.validate(r, now)
        assertEquals(now + 1200000, r.getLong("checkpoint_expected_at_ms"))
        assertEquals(300000, r.getLong("maximum_lateness_ms"))
    }
    @Test fun windowRejectsEarlyLateAndEndedCaptures() {
        val r = report(); FirstCheckpointPolicy.validate(r, now)
        assertTrue(FirstCheckpointPolicy.late(r, now))
        assertFalse(FirstCheckpointPolicy.late(r, now + 1200000))
        assertFalse(FirstCheckpointPolicy.late(r, now + 1500000))
        assertTrue(FirstCheckpointPolicy.late(r, now + 1500001))
        r.put("ends_at_ms", now + 1300000)
        assertTrue(FirstCheckpointPolicy.late(r, now + 1300000))
    }
    @Test fun secondMomentUsesEndMinusTwentyAndIndependentEvidenceField() {
        val r=report().put("moment", "second")
        FirstCheckpointPolicy.validate(r, now)
        assertEquals(now+4800000, r.getLong("checkpoint_expected_at_ms"))
        assertEquals("second_ping", FirstCheckpointPolicy.pingField(r))
        assertEquals("first_ping", FirstCheckpointPolicy.pingField(report()))
        assertTrue(FirstCheckpointPolicy.late(r, now+4799999))
        assertFalse(FirstCheckpointPolicy.late(r, now+4800000))
        assertTrue(FirstCheckpointPolicy.late(r, now+5100001))
    }
    @Test fun unknownMomentsAndSecondBeforeFirstAreRejected() {
        for (r in listOf(report().put("moment", "typo"),
            report().put("moment", "second").put("ends_at_ms", now+2400000))) {
            try { FirstCheckpointPolicy.validate(r,now);fail() } catch (_:IllegalArgumentException) {}
        }
    }
    @Test fun completedFirstIsRetainedUntilThePairEnds() {
        val a=report().put("moment", "first").put("status", "succeeded")
        val b=report().put("moment", "second").put("status", "scheduled")
        assertFalse(FirstCheckpointPolicy.canClear(a,listOf(a),now))
        assertFalse(FirstCheckpointPolicy.canClear(a,listOf(a,b),now))
        assertFalse(FirstCheckpointPolicy.canClear(b,listOf(a,b),now))
        b.put("status", "succeeded")
        assertTrue(FirstCheckpointPolicy.canClear(a,listOf(a,b),now))
        assertTrue(FirstCheckpointPolicy.canClear(a,listOf(a),now+6000000))
        a.put("status", "cancelled")
        assertTrue(FirstCheckpointPolicy.canClear(a,listOf(a),now))
        b.put("campus_id", "other").put("status", "scheduled")
        assertTrue(FirstCheckpointPolicy.canClear(a,listOf(a,b),now))
        assertFalse(FirstCheckpointPolicy.sameRevision(a,b))
        for (field in listOf("course_id","session_id","starts_at_ms","ends_at_ms","campus_id")) {
            assertFalse(FirstCheckpointPolicy.sameRevision(a,JSONObject(a.toString()).put(field,"other")))
        }
    }
    @Test fun areaIncludesEdgesAndSeparatedSites() {
        val r=report()
        assertEquals("no_campus", FirstCheckpointPolicy.classify(r,-20.0,-44.0))
        assertEquals("no_campus", FirstCheckpointPolicy.classify(r,-19.0,-43.0))
        assertEquals("fora", FirstCheckpointPolicy.classify(r,-18.999,-43.5))
        r.getJSONArray("rectangles").put(JSONObject().put("south",-18.0).put("north",-17.0).put("west",-44.0).put("east",-43.0))
        assertEquals("no_campus",FirstCheckpointPolicy.classify(r,-17.5,-43.5))
    }
    @Test fun logsRetainUsefulTerminalFieldsWithoutAreaPayload() {
        val r=report().put("first_ping","no_campus").put("status","succeeded").put("accuracy_m",25.0)
        val log=FirstCheckpointPolicy.logFields(r)
        assertFalse(log.has("rectangles")); assertTrue(r.has("rectangles"))
        assertEquals("no_campus",log.getString("first_ping")); assertEquals(25.0,log.getDouble("accuracy_m"),0.01)
    }
    @Test fun pendingReportsExpireWithoutWaitingForTheScheduler() {
        val r = report(); FirstCheckpointPolicy.validate(r, now)
        r.put("status", "scheduled").put("scheduler", "alarmmanager_exact")
        assertNull(FirstCheckpointPolicy.pendingFailure(r, now, true))
        assertNull(FirstCheckpointPolicy.pendingFailure(r, now + 1500000, true))
        assertEquals("checkpoint_outside_window", FirstCheckpointPolicy.pendingFailure(r, now + 1500001, true))
        assertEquals("exact_alarm_permission_required", FirstCheckpointPolicy.pendingFailure(r, now, false))
        r.put("status", "running")
        assertNull(FirstCheckpointPolicy.pendingFailure(r, now, false))
        r.put("status", "succeeded")
        assertNull(FirstCheckpointPolicy.pendingFailure(r, now + 1500001, false))
        r.put("status", "scheduled").put("ends_at_ms", now + 1300000)
        assertEquals("checkpoint_outside_window", FirstCheckpointPolicy.pendingFailure(r, now + 1300000, true))
    }
    @Test fun malformedSchedulesFailBeforeEnqueue() {
        for (key in listOf("account_id","course_id","session_id","campus_id")) {
            try { FirstCheckpointPolicy.validate(report().put(key,"../../bad"),now);fail(key) } catch (_:IllegalArgumentException) {}
        }
        for ((key,value) in listOf("starts_at_ms" to -1L,"starts_at_ms" to now-1200000,"ends_at_ms" to now+1200000,"starts_at_ms" to now+16000000000L)) {
            try { FirstCheckpointPolicy.validate(report().put(key,value),now);fail(key) } catch (_:IllegalArgumentException) {}
        }
        try { FirstCheckpointPolicy.validate(report().put("rectangles",JSONArray()),now);fail() } catch (_:IllegalArgumentException) {}
        val bad=report();bad.getJSONArray("rectangles").getJSONObject(0).put("north",-21)
        try { FirstCheckpointPolicy.validate(bad,now);fail() } catch (_:IllegalArgumentException) {}
    }
}
