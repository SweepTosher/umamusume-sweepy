package top.mayano.sweepy

import android.Manifest
import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import top.mayano.sweepy.core.JsonCodec

class MainActivity : ComponentActivity() {
    private val runtime: SweepyRuntime by lazy { SweepyApplication.runtime(this) }
    private lateinit var webView: WebView
    private var pendingExportBytes: ByteArray? = null
    private var pendingExportName: String = "umadump.json"

    private val notifPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    private val saveJsonLauncher = registerForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri: Uri? -> writePendingExport(uri) }

    override fun onCreate(savedInstanceState: Bundle?) {
        configureEdgeToEdgeChrome()
        super.onCreate(savedInstanceState)

        webView = createWebView()
        val container = FrameLayout(this).apply {
            setBackgroundColor(BG_COLOR)
            layoutParams = FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT)
            addView(webView)
        }
        ViewCompat.setOnApplyWindowInsetsListener(container) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        setContentView(container)

        restoreOrLoadWebView(savedInstanceState)
        registerBackNavigation()
        requestNotificationsIfNeeded()
    }

    override fun onResume() {
        super.onResume()
        if (::webView.isInitialized) webView.onResume()
        if (runtime.engine.runner.running) {
            SweepyForegroundService.syncState(this, active = true)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::webView.isInitialized) webView.saveState(outState)
    }

    private fun configureEdgeToEdgeChrome() {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }
    }

    private fun createWebView(): WebView {
        val isDebuggable = (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        WebView.setWebContentsDebuggingEnabled(isDebuggable)

        return WebView(this).also { view ->
            view.setBackgroundColor(BG_COLOR)
            view.layoutParams = FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT)
            configureWebSettings(view.settings)
            view.addJavascriptInterface(AndroidJsBridge(), "SweepyAndroid")
            view.webViewClient = LoopbackWebClient()
            view.setDownloadListener { url, _, _, _, _ ->
                if (url.startsWith(runtime.server.url) && "/api/career/final-turn-export" in url) {
                    launchExportPicker()
                } else {
                    openExternalUri(Uri.parse(url))
                }
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebSettings(settings: WebSettings) {
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.setSupportMultipleWindows(false)
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
    }

    private fun restoreOrLoadWebView(savedInstanceState: Bundle?) {
        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState)
        }
        if (webView.url.isNullOrBlank()) {
            webView.loadUrl(runtime.server.url)
        }
    }

    private fun registerBackNavigation() {
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    when {
                        webView.canGoBack() -> webView.goBack()
                        runtime.engine.runner.running -> moveTaskToBack(true)
                        else -> {
                            isEnabled = false
                            onBackPressedDispatcher.onBackPressed()
                        }
                    }
                }
            },
        )
    }

    private inner class LoopbackWebClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
            val uri = request?.url ?: return false
            val host = uri.host?.lowercase()
            val scheme = uri.scheme?.lowercase()
            val isLocalServer = (scheme == "http" || scheme == "https") &&
                (host == "127.0.0.1" || host == "localhost") &&
                uri.port == runtime.server.port
            if (isLocalServer) return false
            openExternalUri(uri)
            return true
        }
    }

    private fun openExternalUri(uri: Uri) {
        val scheme = uri.scheme?.lowercase() ?: return
        if (scheme !in EXTERNAL_SCHEMES) return
        val intent = Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)
        try {
            startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, R.string.err_no_external_app, Toast.LENGTH_SHORT).show()
        }
    }

    private fun launchExportPicker(filenameOverride: String? = null, rawJsonText: String? = null) {
        runtime.ioExecutor.execute {
            val resolved = if (!rawJsonText.isNullOrBlank()) {
                sanitizeExportName(filenameOverride) to rawJsonText
            } else {
                val exp = runCatching { runtime.engine.finalTurnExport() }.getOrNull() ?: return@execute
                sanitizeExportName(exp["filename"]?.toString()) to JsonCodec.encodePretty(exp["json"])
            }
            val bytes = resolved.second.toByteArray(Charsets.UTF_8)
            runOnUiThread {
                pendingExportName = resolved.first
                pendingExportBytes = bytes
                saveJsonLauncher.launch(resolved.first)
            }
        }
    }

    private fun writePendingExport(uri: Uri?) {
        val bytes = pendingExportBytes
        val name = pendingExportName
        pendingExportBytes = null
        if (uri == null || bytes == null) return

        runtime.ioExecutor.execute {
            val saved = runCatching {
                val out = contentResolver.openOutputStream(uri) ?: error("Unable to open destination")
                out.use { stream ->
                    stream.write(bytes)
                    stream.flush()
                }
            }.isSuccess
            runOnUiThread {
                val msg = if (saved) getString(R.string.msg_export_saved, name) else getString(R.string.msg_export_failed)
                Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun sanitizeExportName(raw: String?): String {
        val cleaned = (raw ?: "umadump.json").replace(Regex("[^A-Za-z0-9._-]"), "_").ifBlank { "umadump.json" }
        return if (cleaned.endsWith(".json")) cleaned else "$cleaned.json"
    }

    private fun requestNotificationsIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return
        }
        notifPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private inner class AndroidJsBridge {
        @JavascriptInterface
        fun saveJson(filename: String?, jsonText: String?) {
            if (!jsonText.isNullOrBlank()) {
                launchExportPicker(filenameOverride = filename, rawJsonText = jsonText)
            }
        }
    }

    companion object {
        private const val BG_COLOR = 0xFF080608.toInt()
        private val EXTERNAL_SCHEMES = setOf("https", "http", "steam")
    }
}
