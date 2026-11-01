package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONObject

/** Both checkpoint moments share timing/quality rules; no cloud writes. */
object FirstCheckpointPolicy {
    const val MAX_LATENESS_MS = 300000L
    fun validate(report: JSONObject, now: Long) {
        for (key in listOf("account_id", "course_id", "session_id", "campus_id")) {
            require(report.optString(key).matches(Regex("[A-Za-z0-9_-]{1,128}"))) { "invalid_$key" }
        }
        val start = report.getLong("starts_at_ms")
        val end = report.getLong("ends_at_ms")
        val moment = report.optString("moment", "first")
        require(moment in listOf("first", "second")) { "invalid_checkpoint_moment" }
        require(moment != "second" || end - start > 2400000L) { "second_checkpoint_before_first" }
        val expected = if (moment == "second") end - 1200000L else start + 1200000L
        require(start > 0 && end > expected && expected > now && expected - now <= 15552000000L) { "invalid_checkpoint_time" }
        val areas = report.getJSONArray("rectangles")
        require(areas.length() in 1..3) { "invalid_campus_rectangles" }
        for (i in 0 until areas.length()) {
            val r = areas.getJSONObject(i)
            val south = r.getDouble("south"); val north = r.getDouble("north")
            val west = r.getDouble("west"); val east = r.getDouble("east")
            require(south.isFinite() && north.isFinite() && west.isFinite() && east.isFinite() &&
                south >= -90 && north <= 90 && west >= -180 && east <= 180 && south < north && west < east) { "invalid_campus_rectangle" }
        }
        report.put("moment", moment).put("checkpoint_expected_at_ms", expected).put("maximum_lateness_ms", MAX_LATENESS_MS)
    }
    fun sameRevision(a: JSONObject, b: JSONObject): Boolean =
        listOf("course_id", "session_id", "starts_at_ms", "ends_at_ms", "campus_id", "lesson_count", "call_count")
            .all { a.optString(it) == b.optString(it) }

    fun canClear(report: JSONObject, peers: List<JSONObject>, now: Long): Boolean {
        if (report.optBoolean("delivery_enabled") && !CheckpointDeliveryPolicy.acknowledged(report)) return false
        val active = listOf("scheduled", "running")
        if (report.optString("status") in active) return false
        val related = peers.filter { sameRevision(report, it) }
        if (related.any { it.optBoolean("delivery_enabled") && !CheckpointDeliveryPolicy.acknowledged(it) }) return false
        if (related.any { it.optString("status") in active }) return false
        if (report.optString("status") == "succeeded" && now < report.getLong("ends_at_ms")) {
            return related.any { it.optString("moment", "first") != report.optString("moment", "first") &&
                it.optString("status") !in active }
        }
        return true
    }

    fun pingField(report: JSONObject): String = if (report.optString("moment") == "second") "second_ping" else "first_ping"

    fun late(report: JSONObject, now: Long): Boolean =
        now < report.getLong("checkpoint_expected_at_ms") ||
        now - report.getLong("checkpoint_expected_at_ms") > MAX_LATENESS_MS || now >= report.getLong("ends_at_ms")

    fun pendingFailure(report: JSONObject, now: Long, alarmsAllowed: Boolean): String? {
        if (report.optString("status") !in listOf("scheduled", "running")) return null
        if (now >= report.getLong("ends_at_ms") ||
            now - report.getLong("checkpoint_expected_at_ms") > MAX_LATENESS_MS) return "checkpoint_outside_window"
        if (report.optString("status") == "scheduled" && !alarmsAllowed) return "exact_alarm_permission_required"
        return null
    }
    fun classify(report: JSONObject, latitude: Double, longitude: Double): String {
        val areas = report.getJSONArray("rectangles")
        val inside = (0 until areas.length()).any { i ->
            val r = areas.getJSONObject(i)
            latitude >= r.getDouble("south") && latitude <= r.getDouble("north") &&
                longitude >= r.getDouble("west") && longitude <= r.getDouble("east")
        }
        return if (inside) "no_campus" else "fora"
    }
    fun logFields(report: JSONObject): JSONObject = JSONObject(report.toString()).apply {
        remove("rectangles") // Areas are input, never persist the captured coordinates.
    }
}
