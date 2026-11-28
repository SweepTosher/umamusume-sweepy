package top.mayano.sweepy

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import top.mayano.sweepy.core.JsonCodec

class SweepyForegroundService : Service() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var wakeLock: PowerManager.WakeLock? = null

    private val refreshTick = object : Runnable {
        override fun run() {
            val runtime = SweepyApplication.runtime(this@SweepyForegroundService)
            if (!runtime.engine.runner.running) {
                shutdownService()
                return
            }
            getSystemService(NotificationManager::class.java)
                ?.notify(NOTIF_ID, buildNotification(runtime))
            mainHandler.postDelayed(this, TICK_INTERVAL_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val runtime = SweepyApplication.runtime(this)
        ServiceCompat.startForeground(
            this,
            NOTIF_ID,
            buildNotification(runtime),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
        )

        if (intent?.action == ACTION_STOP_RUN) {
            runtime.ioExecutor.execute {
                runCatching { runtime.engine.stopRunner() }
                mainHandler.post { shutdownService() }
            }
            return START_NOT_STICKY
        }

        if (!runtime.engine.runner.running) {
            shutdownService()
            return START_NOT_STICKY
        }

        ensureWakeLock()
        mainHandler.removeCallbacks(refreshTick)
        mainHandler.postDelayed(refreshTick, TICK_INTERVAL_MS)
        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        val runtime = SweepyApplication.runtime(this)
        runtime.ioExecutor.execute { runCatching { runtime.engine.stopRunner() } }
        shutdownService()
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(refreshTick)
        releaseWakeLock()
        super.onDestroy()
    }

    private fun ensureWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(PowerManager::class.java) ?: return
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sweepy:career").apply {
            setReferenceCounted(false)
            acquire(WAKELOCK_TIMEOUT_MS)
        }
    }

    private fun releaseWakeLock() {
        val held = wakeLock ?: return
        wakeLock = null
        if (held.isHeld) held.release()
    }

    private fun shutdownService() {
        mainHandler.removeCallbacks(refreshTick)
        releaseWakeLock()
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun buildNotification(runtime: SweepyRuntime): Notification {
        val snap = runtime.engine.runner.snapshot()
        val turn = JsonCodec.asInt(snap["turn"], 0)
        val lastAction = (snap["last_action"] ?: "Running career").toString()
        val stats = JsonCodec.asMap(snap["stats"])
        val spd = JsonCodec.asInt(stats?.get("speed"), 0)
        val wit = JsonCodec.asInt(stats?.get("wit"), 0)

        val title = if (turn > 0) "Sweepy · Turn $turn/78" else "Sweepy · Career Active"
        val body = if (turn > 0 && (spd > 0 || wit > 0)) {
            "$lastAction · SPD $spd · WIT $wit"
        } else {
            lastAction
        }

        val openIntent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val openPending = PendingIntent.getActivity(this, 0, openIntent, PENDING_FLAGS)

        val stopIntent = Intent(this, SweepyForegroundService::class.java)
            .setAction(ACTION_STOP_RUN)
        val stopPending = PendingIntent.getService(this, 1, stopIntent, PENDING_FLAGS)

        return NotificationCompat.Builder(this, SweepyApplication.NOTIF_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_sweepy)
            .setContentTitle(title)
            .setContentText(body)
            .setContentIntent(openPending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .addAction(0, getString(R.string.notif_stop_action), stopPending)
            .build()
    }

    companion object {
        private const val NOTIF_ID = 3901
        private const val TICK_INTERVAL_MS = 2500L
        private const val WAKELOCK_TIMEOUT_MS = 4L * 60L * 60L * 1000L
        private const val ACTION_STOP_RUN = "top.mayano.sweepy.action.STOP_RUN"
        private const val PENDING_FLAGS = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

        fun syncState(context: Context, active: Boolean) {
            val intent = Intent(context, SweepyForegroundService::class.java)
            if (active) {
                runCatching { ContextCompat.startForegroundService(context, intent) }
            } else {
                context.stopService(intent)
            }
        }
    }
}
