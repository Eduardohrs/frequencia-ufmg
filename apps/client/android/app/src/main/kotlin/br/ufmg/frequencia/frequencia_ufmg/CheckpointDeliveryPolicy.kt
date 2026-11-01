package br.ufmg.frequencia.frequencia_ufmg

import org.json.JSONObject
import java.security.MessageDigest

/** Pure queue rules; location classification remains in the canonical Python domain. */
object CheckpointDeliveryPolicy {
    private val terminal = setOf("applied", "already_applied", "preserved", "unresolved", "discarded", "rejected")
    fun acknowledged(report: JSONObject) = report.optString("delivery_status") in terminal
    private fun latest(seed: JSONObject, reports: List<JSONObject>, moment: String): JSONObject? = reports
        .filter { it.optString("account_id") == seed.optString("account_id") &&
            FirstCheckpointPolicy.sameRevision(seed, it) && it.optString("moment", "first") == moment }
        .maxByOrNull { it.optLong("scheduled_at_ms") }
    fun allAcknowledged(seed: JSONObject, reports: List<JSONObject>): Boolean {
        val related = reports.filter { it.optString("account_id") == seed.optString("account_id") &&
            FirstCheckpointPolicy.sameRevision(seed, it) && it.optBoolean("delivery_enabled") }
        return related.isNotEmpty() && related.all { acknowledged(it) }
    }
    fun workName(report: JSONObject): String {
        val revision = listOf("account_id", "course_id", "session_id", "starts_at_ms", "ends_at_ms", "campus_id", "lesson_count", "call_count")
            .joinToString("/") { report.get(it).toString() }
        return "checkpoint_delivery_" + MessageDigest.getInstance("SHA-256").digest(revision.toByteArray())
            .joinToString("") { "%02x".format(it) }
    }
    fun readyAt(seed: JSONObject, reports: List<JSONObject>, now: Long): Long {
        var ready = now
        for (moment in listOf("first", "second")) {
            val r = latest(seed, reports, moment)
            if (r == null || r.optString("status") in listOf("scheduled", "running")) {
                val expected = if (moment == "first") seed.getLong("starts_at_ms") + 1200000L else seed.getLong("ends_at_ms") - 1200000L
                ready = maxOf(ready, minOf(expected + FirstCheckpointPolicy.MAX_LATENESS_MS + 1, seed.getLong("ends_at_ms")))
            }
        }
        return ready
    }
    fun payload(seed: JSONObject, reports: List<JSONObject>): JSONObject {
        val result = JSONObject()
        for (key in listOf("starts_at_ms", "ends_at_ms", "lesson_count", "call_count", "campus_id")) result.put(key, seed.get(key))
        for (moment in listOf("first", "second")) {
            val r = latest(seed, reports, moment)
            result.put(moment, if (r == null) JSONObject.NULL else JSONObject()
                .put("operation_id", r.getString("operation_id")).put("status", r.getString("status"))
                .put("ping", r.optString(FirstCheckpointPolicy.pingField(r), "indisponivel"))
                .put("expected_at_ms", r.getLong("checkpoint_expected_at_ms"))
                .put("captured_at_ms", r.opt("captured_at_ms") ?: JSONObject.NULL))
        }
        return result
    }
    fun httpOutcome(status: Int, body: JSONObject): String {
        if (status == 200 && body.optString("outcome") in terminal) return body.getString("outcome")
        if (status == 404 && body.optString("error") == "session_not_found") return "discarded"
        if (status == 400 && body.optString("error") == "checkpoint_rejected") return "rejected"
        return "retry"
    }
    fun confirmedOutcome(status: Int, response: JSONObject, request: JSONObject): String {
        val outcome = httpOutcome(status, response)
        if (status == 200 && outcome != "retry") {
            for (moment in listOf("first", "second")) {
                val expected = request.optJSONObject(moment)?.optString("operation_id")
                val confirmed = if (response.isNull(moment + "_operation_id")) null else response.optString(moment + "_operation_id")
                if (expected != confirmed) return "retry"
            }
        }
        return outcome
    }
    fun failureDetails(error: Throwable): JSONObject {
        var root = error
        repeat(4) { root = root.cause ?: root }
        fun safe(message: String?): String {
            var result = message.orEmpty()
            result = Regex("""(?i)\bBearer\s+[^\s,;]+""").replace(result, "Bearer [redacted]")
            result = Regex("""(?i)\b(password|token|access_token|refresh_token|api_key|key)\s*[=:]\s*["']?[^"\s';,}]+""")
                .replace(result) { it.groupValues[1] + "=[redacted]" }
            result = Regex("""eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+""").replace(result, "[redacted]")
            return result.take(600)
        }
        return JSONObject().put("cause_type", error.javaClass.simpleName).put("cause_message", safe(error.message))
            .put("root_cause_type", root.javaClass.simpleName).put("root_cause_message", safe(root.message))
    }
}
