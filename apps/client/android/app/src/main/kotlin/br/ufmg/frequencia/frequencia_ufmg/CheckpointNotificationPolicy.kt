package br.ufmg.frequencia.frequencia_ufmg
import org.json.JSONObject
import java.security.MessageDigest

object CheckpointNotificationPolicy {
    data class Notice(val kind:String,val operations:List<String>) {
        val fingerprint:String get()=MessageDigest.getInstance("SHA-256").digest((kind+":"+operations.joinToString(",")).toByteArray()).joinToString("") { "%02x".format(it) }
        val body:String get()=when(kind) {
            "manual" -> "Não foi possível definir uma frequência. Abra o aplicativo para revisar."
            "capture" -> "Uma verificação de localização falhou ou perdeu o horário. Revise a frequência."
            "upload" -> "Há resultados aguardando envio. O aplicativo tentará novamente."
            "test" -> "Aviso de teste. Toque para abrir os pings de presença."
            else -> "Um registro automático precisa de revisão. Confira no aplicativo."
        }
    }
    private fun kind(r:JSONObject):String? {
        return when(r.optString("delivery_status")) {
            "preserved","discarded" -> null
            "applied","already_applied" -> if(r.optString("delivery_attendance_status") in listOf("ausente","chegou_atrasado","saiu_mais_cedo")) "review" else null
            "unresolved","rejected" -> "manual"
            "retry" -> "upload"
            else -> if(r.optString("status") !in listOf("","scheduled","running","succeeded","cancelled","superseded")) "capture" else null
        }
    }
    fun select(account:String,reports:List<JSONObject>,reviewed:Set<String> = emptySet()):Notice? {
        val issues=reports.filter { it.optString("account_id")==account && it.optString("operation_id") !in reviewed }.mapNotNull { r -> kind(r)?.let { it to r.optString("operation_id") } }
        if(issues.isEmpty()) return null
        val strongest=issues.maxBy { listOf("review","upload","capture","manual").indexOf(it.first) }.first
        return Notice(strongest,issues.map { it.second }.distinct().sorted())
    }
    fun decision(fingerprint:String?,previous:String,previousOutcome:String,allowed:Boolean,channelAllowed:Boolean):String=when {
        fingerprint==null -> "clear"
        !allowed -> "blocked_permission"
        !channelAllowed -> "blocked_channel"
        fingerprint==previous && previousOutcome=="posted" -> "unchanged"
        else -> "post"
    }
    fun canOpen(active:String?,owner:String?,token:String,previous:String)=active!=null && active==owner && token.length in 1..128 && token!=previous
}
