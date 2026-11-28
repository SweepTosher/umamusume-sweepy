package top.mayano.sweepy

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.res.AssetManager
import android.os.Handler
import android.os.Looper
import okhttp3.OkHttpClient
import top.mayano.sweepy.core.AssetSource
import top.mayano.sweepy.core.LocalHttpServer
import top.mayano.sweepy.core.RuntimeStore
import top.mayano.sweepy.core.SweepyEngine
import java.io.Closeable
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

private class AssetManagerSource(private val assets: AssetManager) : AssetSource {
    override fun readBytes(relativePath: String): ByteArray? = runCatching {
        assets.open(relativePath.trimStart('/')).use { it.readBytes() }
    }.getOrNull()
}

class SweepyRuntime(private val appContext: Context) : Closeable {
    val store = RuntimeStore(appContext.filesDir.toPath().resolve("uma_runtime"))
    val ioExecutor: ExecutorService = Executors.newCachedThreadPool { task ->
        Thread(task, "sweepy-io").apply { isDaemon = true }
    }
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val mainHandler = Handler(Looper.getMainLooper())
    val engine: SweepyEngine = SweepyEngine(store, AssetManagerSource(appContext.assets), http) { active ->
        mainHandler.post { SweepyForegroundService.syncState(appContext, active) }
    }
    val server = LocalHttpServer(engine, requestedPort = 0)

    override fun close() {
        runCatching { server.close() }
        runCatching { engine.close() }
        ioExecutor.shutdownNow()
        http.dispatcher.executorService.shutdown()
        http.connectionPool.evictAll()
    }
}

class SweepyApplication : Application() {
    val runtime: SweepyRuntime by lazy { SweepyRuntime(applicationContext) }

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(NOTIF_CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            NOTIF_CHANNEL_ID,
            getString(R.string.notif_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.notif_channel_desc)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    companion object {
        const val NOTIF_CHANNEL_ID = "sweepy_career"

        fun runtime(context: Context): SweepyRuntime =
            (context.applicationContext as SweepyApplication).runtime
    }
}
