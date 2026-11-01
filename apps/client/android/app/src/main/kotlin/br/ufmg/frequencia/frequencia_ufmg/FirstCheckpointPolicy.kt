package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONObject

/** First checkpoint only; no attendance classification or cloud writes. */
object FirstCheckpointPolicy {
    const val MAX_LATENESS_MS = 300000L
    fun validate(report: JSONObject, now: Long) {
        for (key in listOf("account_id", "course_id", "session_id", "campus_id")) {
            require(report.optString(key).matches(Regex("[A-Za-z0-9_-]{1,128}"))) { "invalid_$key" }
        }
        val start = report.getLong("starts_at_ms")
        val end = report.getLong("ends_at_ms")
        val expected = start + 1200000L
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
        report.put("checkpoint_expected_at_ms", expected).put("maximum_lateness_ms", MAX_LATENESS_MS)
    }
    fun late(report: JSONObject, now: Long): Boolean =
        now < report.getLong("checkpoint_expected_at_ms") ||
        now - report.getLong("checkpoint_expected_at_ms") > MAX_LATENESS_MS || now >= report.getLong("ends_at_ms")

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
