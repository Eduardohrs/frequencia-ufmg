package br.ufmg.frequencia.frequencia_ufmg

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** One replaceable local notice; notification failures never block attendance. */
object CheckpointNotifications {
    const val ACTION="br.ufmg.frequencia.OPEN_CHECKPOINTS"
    const val CHANNEL="attendance_review"
    const val ID=48002
    const val TEST_ID=48003
    private const val STORE="checkpoint_notices"
    fun reviewed(c:Context):Set<String> = prefs(c).getStringSet("reviewed",emptySet())!!.toSet()
    private fun prefs(c:Context)=c.getSharedPreferences(STORE,0)
    private fun manager(c:Context)=c.getSystemService(NotificationManager::class.java)
    private fun channel(c:Context):Boolean {
        if(Build.VERSION.SDK_INT<26) return true
        val m=manager(c)
        m.createNotificationChannel(NotificationChannel(CHANNEL,"Revisão de frequência",NotificationManager.IMPORTANCE_DEFAULT))
        return m.getNotificationChannel(CHANNEL).importance!=NotificationManager.IMPORTANCE_NONE
    }
    private fun record(c:Context,account:String,event:String,outcome:String,notice:CheckpointNotificationPolicy.Notice?,started:Long,error:Exception?=null,noticeToken:String?=null) {
        val r=JSONObject().put("event",event).put("account_id",account).put("operation_id",UUID.randomUUID().toString())
            .put("stage","notification").put("status",outcome).put("occurred_at_ms",System.currentTimeMillis())
            .put("duration_ms",System.currentTimeMillis()-started).put("kind",notice?.kind ?: "none")
            .put("checkpoint_operations",JSONArray(notice?.operations ?: emptyList<String>()))
        if(noticeToken!=null) r.put("notification_id",noticeToken)
        if(error!=null) r.put("failure",CheckpointDeliveryPolicy.failureDetails(error))
        try {
            val p=prefs(c);val old=JSONArray(p.getString("reports","[]"));val rows=JSONArray()
            for(i in maxOf(0,old.length()-19) until old.length()) rows.put(old.get(i))
            rows.put(r);check(p.edit().putString("reports",rows.toString()).commit())
        } catch(error:Exception) { r.put("history_failure",CheckpointDeliveryPolicy.failureDetails(error)) }
        BackgroundLocationProof.emit(r)
    }
    private fun publish(c:Context,account:String,notice:CheckpointNotificationPolicy.Notice,test:Boolean):String {
        val id=if(test)TEST_ID else ID
        val token=UUID.randomUUID().toString()
        val intent=Intent(c,MainActivity::class.java).setAction(ACTION)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra("checkpoint_owner",account).putExtra("checkpoint_notice",token)
            .putStringArrayListExtra("checkpoint_operations",ArrayList(notice.operations))
        val open=PendingIntent.getActivity(c,id,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val public=NotificationCompat.Builder(c,CHANNEL).setSmallIcon(c.applicationInfo.icon)
            .setContentTitle("Frequência UFMG").setContentText("Abra o aplicativo para revisar um aviso.").build()
        val notification=NotificationCompat.Builder(c,CHANNEL).setSmallIcon(c.applicationInfo.icon)
            .setContentTitle(if(test)"Teste de aviso de frequência" else "Frequência: revisão necessária")
            .setContentText(notice.body).setStyle(NotificationCompat.BigTextStyle().bigText(notice.body))
            .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true).setLocalOnly(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public).build()
        manager(c).notify(id,notification)
        return token
    }
    fun refresh(c:Context) = synchronized(FirstCheckpointBridge.LOCK) {
        val started=System.currentTimeMillis()
        val index=c.getSharedPreferences(FirstCheckpointBridge.INDEX,0)
        val account=index.getString("account_id",null) ?: return@synchronized
        var notice:CheckpointNotificationPolicy.Notice?=null
        try {
            val reports=index.getStringSet("stores",emptySet())!!.map { key ->
                JSONObject(c.getSharedPreferences(key,0).getString("report","{}")!!)
            }
            notice=CheckpointNotificationPolicy.select(account,reports,prefs(c).getStringSet("reviewed",emptySet())!!)
            val p=prefs(c)
            val allowed=NotificationManagerCompat.from(c).areNotificationsEnabled()
            val decision=CheckpointNotificationPolicy.decision(notice?.fingerprint,p.getString("fingerprint","")!!,p.getString("outcome","")!!,allowed,channel(c))
            if(decision=="unchanged") return@synchronized
            var noticeToken:String?=null
            if(decision=="clear") {
                manager(c).cancel(ID)
                if(p.getString("outcome","")=="cleared") return@synchronized
            } else if(decision=="post") noticeToken=publish(c,account,notice!!,false)
            val outcome=if(decision=="post")"posted" else if(decision=="clear")"cleared" else decision
            if(outcome!=p.getString("outcome","") || notice?.fingerprint!=p.getString("fingerprint","")) {
                check(p.edit().putString("fingerprint",notice?.fingerprint ?: "").putString("outcome",outcome).commit())
                record(c,account,"checkpoint_notification",outcome,notice,started,noticeToken=noticeToken)
            }
        } catch(error:Exception) { record(c,account,"checkpoint_notification","failed",notice,started,error) }
    }
    fun test(c:Context,account:String) = synchronized(FirstCheckpointBridge.LOCK) {
        val start=System.currentTimeMillis();val notice=CheckpointNotificationPolicy.Notice("test",emptyList())
        try {
            check(FirstCheckpointBridge.active(c,account)) { "notification_owner_changed" }
            check(NotificationManagerCompat.from(c).areNotificationsEnabled()) { "notifications_disabled" }
            check(channel(c)) { "notification_channel_disabled" }
            val noticeToken=publish(c,account,notice,true)
            record(c,account,"checkpoint_notification","posted",notice,start,noticeToken=noticeToken)
        } catch(error:Exception) { record(c,account,"checkpoint_notification","failed",notice,start,error);throw error }
    }
    fun reports(c:Context,account:String):List<Map<String,Any?>> = try {
        val rows=JSONArray(prefs(c).getString("reports","[]"))
        (0 until rows.length()).map { rows.getJSONObject(it) }.filter { it.optString("account_id")==account }
            .map { mapOf("notification_report" to FirstCheckpointPolicy.channelFields(it)) }
     } catch(error:Exception) {
        BackgroundLocationProof.emit(JSONObject().put("event","checkpoint_notification_history_failed").put("account_id",account).put("failure",CheckpointDeliveryPolicy.failureDetails(error)))
        emptyList()
    }
    fun opened(c:Context,intent:Intent?) = synchronized(FirstCheckpointBridge.LOCK) {
        if(intent?.action!=ACTION) return@synchronized
        val index=c.getSharedPreferences(FirstCheckpointBridge.INDEX,0)
        val account=index.getString("account_id",null);val owner=intent.getStringExtra("checkpoint_owner")
        val token=intent.getStringExtra("checkpoint_notice") ?: ""
        if(!CheckpointNotificationPolicy.canOpen(account,owner,token,index.getString("last_notice_open","")!!)) return@synchronized
        val current=index.getStringSet("stores",emptySet())!!.map { key -> JSONObject(c.getSharedPreferences(key,0).getString("report","{}")!!).optString("operation_id") }.toSet()
        val reviewed=prefs(c).getStringSet("reviewed",emptySet())!!.toMutableSet()
        reviewed.retainAll(current)
        reviewed.addAll((intent.getStringArrayListExtra("checkpoint_operations") ?: arrayListOf()).take(50).filter { it in current })
        check(prefs(c).edit().putStringSet("reviewed",reviewed).commit())
        check(index.edit().putString("last_notice_open",token).putBoolean("notice_open_pending",true)
            .putLong(CheckpointDeliveryEvents.OPEN_REVISION,index.getLong(CheckpointDeliveryEvents.OPEN_REVISION,0)+1).commit())
        manager(c).cancel(TEST_ID)
        record(c,account!!,"checkpoint_notification_opened","opened",null,System.currentTimeMillis(),noticeToken=token)
    }
    fun clear(c:Context) {
        try { manager(c).cancel(ID);manager(c).cancel(TEST_ID);prefs(c).edit().clear().apply() }
        catch(error:Exception) { BackgroundLocationProof.emit(JSONObject().put("event","checkpoint_notification").put("status","clear_failed").put("failure",CheckpointDeliveryPolicy.failureDetails(error))) }
    }
}
