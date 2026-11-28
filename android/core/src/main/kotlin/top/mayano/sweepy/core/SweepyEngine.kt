package top.mayano.sweepy.core

import okhttp3.OkHttpClient
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.EOFException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.net.URLDecoder
import java.nio.file.Files
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

class SweepyEngine(
    val store: RuntimeStore,
    val assets: AssetSource,
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build(),
    var onRunnerStateChanged: ((Boolean) -> Unit)? = null,
) : Closeable {
    val catalog = Catalog(assets)
    val runner = CareerRunner(
        accountSalt = store.accountSalt(),
        runtimeDir = store.runtimeDir,
        catalog = catalog,
        onRunningChanged = { active -> onRunnerStateChanged?.invoke(active) },
    ).also { r ->
        r.setBurnClocks(store.loadSettings().burnClocks)
    }

    private val stateLock = Any()
    private val authLock = ReentrantLock()

    private var provider: SteamTicketProvider? = null
    private var client: UmaClient? = null
    private var rawAccountData: LinkedHashMap<String, Any?>? = null
    private var dashboard: LinkedHashMap<String, Any?>? = null
    private var deviceState: DeviceStateRecord? = readDiskDeviceState()
    private var brainOnline: Boolean = false
    private var brainHealth: Map<String, Any?>? = null
    private var brainProbeAtMs: Long = 0L
    private var syncedFinishedMarker: Int? = null
    private var lastQrUrl: String = ""

    private fun readDiskDeviceState(): DeviceStateRecord? =
        runCatching { DeviceIdentity.readDeviceState(store.deviceFile) }.getOrNull()

    private fun getProvider(token: String? = null): SteamTicketProvider = synchronized(stateLock) {
        if (!token.isNullOrBlank() && provider != null) {
            provider?.close()
            provider = null
        }
        provider ?: SteamTicketProvider(store, http, token = token).also { provider = it }
    }

    private fun applyTurnDelay(c: UmaClient, delay: TurnDelayConfig) {
        c.timing?.let { t ->
            t.disabled = delay.disabled
            if (!t.disabled) {
                t.turnMin = delay.min
                t.turnMax = delay.max
            }
        }
    }

    private fun completeUmaLogin(prov: SteamTicketProvider): LinkedHashMap<String, Any?> = authLock.withLock {
        val already = synchronized(stateLock) { client != null && dashboard != null }
        if (already) {
            return sessionPayload().apply {
                put("status", "approved")
                put("logged_in", true)
            }
        }
        val (umaClient, bootRes) = UmaClient.bootstrapHeadlessAuth(
            store = store,
            http = http,
            provider = prov,
            deviceState = deviceState,
            persistDevice = true,
        )
        try {
            val settings = store.loadSettings()
            applyTurnDelay(umaClient, settings.turnDelay)
            val bootInner = StateStripper.unwrapData(bootRes)
            val rawData = if (listOf("user_info", "card_list", "tp_info").any { it in bootInner }) {
                LinkedHashMap(bootInner)
            } else {
                LinkedHashMap(StateStripper.unwrapData(umaClient.login(readInfo = true)))
            }
            if (rawData.isEmpty()) throw IllegalStateException("Login returned no account data")

            val activeLight = JsonCodec.asMap(rawData["single_mode_chara_light"] ?: rawData["single_mode_chara"])
            val careerRes = if (activeLight != null && JsonCodec.asInt(activeLight["scenario_id"], 0) == 3) {
                runCatching { umaClient.loadCareer(3) }.getOrNull()
            } else {
                null
            }
            val dash = catalog.formatAccountStatus(rawData, careerData = careerRes)
            val devRec = umaClient.deviceState
            val oldClient: UmaClient?
            synchronized(stateLock) {
                oldClient = client
                client = umaClient
                rawAccountData = rawData
                dashboard = dash
                if (devRec != null) deviceState = devRec
            }
            if (oldClient != null && oldClient !== umaClient) {
                oldClient.close()
            }
        } catch (t: Throwable) {
            umaClient.close()
            throw t
        }
        sessionPayload().apply {
            put("status", "approved")
            deviceState?.let { put("device_state", it.toMap()) }
        }
    }

    private fun syncRunnerSettlement() {
        val (latest0, marker) = runner.latestAccountSnapshot()
        if (latest0 == null) return
        synchronized(stateLock) {
            if (syncedFinishedMarker == marker) return
            syncedFinishedMarker = marker
            val latest = LinkedHashMap(latest0)
            val existingVets = rawAccountData?.get("trained_chara_array")
            if (existingVets != null && latest["trained_chara_array"] == null) {
                latest["trained_chara_array"] = existingVets
            }
            rawAccountData = latest
            dashboard = catalog.formatAccountStatus(latest)
        }
    }

    private fun accountView(runnerSnap: Map<String, Any?>): LinkedHashMap<String, Any?>? {
        val (dash, logged) = synchronized(stateLock) {
            val d = dashboard?.let { JsonCodec.asMutableMap(JsonCodec.deepCopy(it)) }
            d to (client != null && d != null)
        }
        if (!logged || dash == null) return null
        val career = JsonCodec.asMutableMap(dash["career"])
        val liveTurn = JsonCodec.asInt(runnerSnap["turn"], 0)
        if (career != null && liveTurn > JsonCodec.asInt(career["turn"], 0)) {
            career["turn"] = liveTurn
            dash["career"] = career
        }
        return dash as? LinkedHashMap<String, Any?>
    }

    private fun refreshBrainStatus(settings: RuntimeSettings) {
        if (settings.apiKey.isEmpty() || settings.apiUrl.isEmpty()) {
            synchronized(stateLock) {
                brainOnline = false
                brainHealth = null
            }
            return
        }
        val now = System.nanoTime() / 1_000_000L
        synchronized(stateLock) {
            if (now - brainProbeAtMs < 5000L) return
            brainProbeAtMs = now
        }
        try {
            BrainClient(settings.apiUrl, settings.apiKey, http, timeoutSec = 3L).use { brain ->
                val health = brain.health()
                synchronized(stateLock) {
                    brainOnline = true
                    brainHealth = health
                }
            }
        } catch (_: Exception) {
            synchronized(stateLock) {
                brainOnline = false
                brainHealth = null
            }
        }
    }

    private fun refreshAccount(force: Boolean) {
        if (!force) return
        val skip = synchronized(stateLock) { client == null || dashboard == null || runner.running }
        if (skip) return
        if (!authLock.tryLock()) return
        try {
            val c = synchronized(stateLock) {
                if (runner.running) return
                client ?: return
            }
            val raw = runCatching { c.login(readInfo = true) }.getOrNull() ?: return
            val data = StateStripper.unwrapData(raw)
            if (data.isEmpty()) return
            val light = JsonCodec.asMap(data["single_mode_chara_light"] ?: data["single_mode_chara"])
            val careerRes = if (light != null && JsonCodec.asInt(light["scenario_id"], 0) == 3) {
                runCatching { c.loadCareer(3) }.getOrNull()
            } else {
                null
            }
            val dash = catalog.formatAccountStatus(data, careerData = careerRes)
            synchronized(stateLock) {
                rawAccountData = LinkedHashMap(data)
                dashboard = dash
            }
        } finally {
            authLock.unlock()
        }
    }

    fun sessionPayload(refresh: Boolean = false): LinkedHashMap<String, Any?> {
        syncRunnerSettlement()
        refreshAccount(force = refresh)
        val settings = store.loadSettings()
        refreshBrainStatus(settings)
        val runnerSnap = runner.snapshot()
        val (logged, bOnline, bHealth, rawAcc) = synchronized(stateLock) {
            SessionSnapshotState(
                loggedIn = client != null && dashboard != null,
                brainOnline = brainOnline,
                brainHealth = brainHealth?.let { LinkedHashMap(it) },
                rawAccount = rawAccountData?.let { LinkedHashMap(it) },
            )
        }
        val cmEnabled = AppConstants.CM_ENABLED
        val cmCfg = LinkedHashMap(settings.cmConfig)
        if (!cmEnabled) cmCfg["cm_mode"] = false

        return linkedMapOf(
            "ok" to true,
            "logged_in" to logged,
            "password_auth" to true,
            "brain" to linkedMapOf(
                "api_url" to settings.apiUrl,
                "has_api_key" to settings.apiKey.isNotEmpty(),
                "api_key_masked" to maskApiKey(settings.apiKey),
                "online" to bOnline,
                "health" to bHealth,
                "api_key_seed" to "",
            ),
            "api_url" to settings.apiUrl,
            "has_api_key" to settings.apiKey.isNotEmpty(),
            "turn_delay" to settings.turnDelay.toMap(),
            "burn_clocks" to settings.burnClocks,
            "cm_enabled" to cmEnabled,
            "cm_config" to cmCfg,
            "cm_catalog" to if (cmEnabled) catalog.cmMetadata() else null,
            "veterans" to if (cmEnabled && logged && rawAcc != null) catalog.formatVeterans(rawAcc) else emptyList<Any>(),
            "device_state" to deviceState?.toMap(),
            "runner" to runnerSnap,
            "account" to accountView(runnerSnap),
        )
    }

    fun configureBrain(body: Map<String, Any?>): LinkedHashMap<String, Any?> {
        val apiUrl = store.loadSettings().apiUrl
        val apiKey = (body["api_key"] ?: "").toString().trim()
        if (apiKey.isEmpty()) throw IllegalArgumentException("Enter an API key")
        val health = try {
            BrainClient(apiUrl, apiKey, http, timeoutSec = 3L).use { it.health() }
        } catch (exc: BrainApiException) {
            synchronized(stateLock) {
                brainOnline = false
                brainHealth = null
            }
            throw exc
        }
        val saved = store.setBrainConfig(apiUrl, apiKey)
        synchronized(stateLock) {
            brainOnline = true
            brainHealth = health
        }
        return linkedMapOf(
            "ok" to true,
            "online" to true,
            "api_url" to saved.apiUrl,
            "has_api_key" to saved.apiKey.isNotEmpty(),
            "health" to health,
        )
    }

    private fun finishSteamApproval(prov: SteamTicketProvider): LinkedHashMap<String, Any?> {
        try {
            prov.ensureLease()
        } catch (exc: SteamTicketException) {
            return steamErrorPayload(exc)
        }
        val already = synchronized(stateLock) { client != null }
        if (!already) forgetDeviceState()
        val payload = completeUmaLogin(prov)
        runCatching { prov.currentToken() }.getOrNull()?.takeIf { it.isNotEmpty() }?.let {
            payload["refresh_token"] = it
        }
        payload["status"] = "approved"
        payload["logged_in"] = true
        return payload
    }

    private fun requireLoggedOutForAuth(actionLabel: String) {
        if (runner.running) throw IllegalStateException("Stop the run before $actionLabel")
        synchronized(stateLock) {
            if (client != null) throw IllegalStateException("Log out before signing into a new account")
        }
    }

    fun qrStart(): LinkedHashMap<String, Any?> = authLock.withLock {
        requireLoggedOutForAuth("QR login")
        val prov = getProvider()
        val info = try {
            prov.startQrSession()
        } catch (exc: SteamTicketException) {
            return steamErrorPayload(exc)
        }
        val url = (info["challenge_url"] ?: "").toString()
        if (url.isEmpty()) throw IllegalStateException("Steam returned no QR URL")
        val svg = QrSvg.renderQrSvg(url)
        synchronized(stateLock) { lastQrUrl = url }
        linkedMapOf(
            "ok" to true,
            "challenge_url" to url,
            "qr_svg" to svg,
            "interval" to (info["interval"] ?: 2),
        )
    }

    private fun resolveSteamApproval(
        prov: SteamTicketProvider,
        res: Map<String, Any?>,
        body: Map<String, Any?> = emptyMap(),
    ): LinkedHashMap<String, Any?> {
        if (body["defer_login"] == true) {
            val out = linkedMapOf<String, Any?>(
                "ok" to true,
                "status" to "steam_approved",
                "logged_in" to false,
                "steam_id" to res["steam_id"],
            )
            runCatching { prov.currentToken() }.getOrNull()?.takeIf { it.isNotEmpty() }?.let {
                out["refresh_token"] = it
            }
            return out
        }
        return finishSteamApproval(prov)
    }

    fun finalizeSteamLogin(): LinkedHashMap<String, Any?> = authLock.withLock {
        val already = synchronized(stateLock) { client != null && dashboard != null }
        if (already) {
            return sessionPayload().apply {
                put("status", "approved")
                put("logged_in", true)
            }
        }
        val prov = getProvider()
        return try {
            check(prov.hasRefreshToken()) { "No approved Steam session to finalize" }
            finishSteamApproval(prov)
        } catch (exc: SteamTicketException) {
            steamErrorPayload(exc)
        }
    }

    fun credentialsStart(body: Map<String, Any?>): LinkedHashMap<String, Any?> = authLock.withLock {
        requireLoggedOutForAuth("signing in")
        val username = (body["username"] ?: "").toString()
        val password = (body["password"] ?: "").toString()
        val prov = getProvider()
        val res = try {
            prov.startCredentialsSession(username, password)
        } catch (exc: SteamTicketException) {
            return steamErrorPayload(exc)
        }
        if ((res["status"] ?: "").toString() == "approved") {
            return resolveSteamApproval(prov, res, body)
        }
        return LinkedHashMap(res).apply { put("ok", true) }
    }

    fun credentialsSubmitCode(body: Map<String, Any?>): LinkedHashMap<String, Any?> = authLock.withLock {
        requireLoggedOutForAuth("verifying Steam Guard")
        val code = (body["code"] ?: "").toString()
        val codeType = JsonCodec.asLongOrNull(body["code_type"])?.toInt()
        val prov = getProvider()
        val res = try {
            prov.submitSteamGuardCode(code, codeType)
        } catch (exc: SteamTicketException) {
            return steamErrorPayload(exc)
        }
        if ((res["status"] ?: "").toString() == "approved") {
            return resolveSteamApproval(prov, res, body)
        }
        return LinkedHashMap(res).apply { put("ok", true) }
    }

    fun qrPoll(body: Map<String, Any?> = emptyMap()): LinkedHashMap<String, Any?> = authLock.withLock {
        val prov = getProvider()
        val res = try {
            prov.pollQrSession()
        } catch (exc: SteamTicketException) {
            return steamErrorPayload(exc)
        }
        val st = (res["status"] ?: "pending").toString()
        if (st == "approved") {
            return resolveSteamApproval(prov, res, body)
        }
        val challengeUrl = (res["challenge_url"] ?: "").toString()
        val out = linkedMapOf<String, Any?>(
            "ok" to true,
            "status" to st,
            "challenge_url" to challengeUrl,
            "steam_id" to res["steam_id"],
            "interval" to res["interval"],
            "had_remote_interaction" to (res["had_remote_interaction"] == true),
        )
        if (challengeUrl.isNotEmpty()) {
            val changed = synchronized(stateLock) {
                (challengeUrl != lastQrUrl).also { if (it) lastQrUrl = challengeUrl }
            }
            if (changed) out["qr_svg"] = QrSvg.renderQrSvg(challengeUrl)
        }
        return out
    }

    fun restoreSession(body: Map<String, Any?> = emptyMap()): LinkedHashMap<String, Any?> {
        val bodyKey = (body["api_key"] ?: "").toString().trim()
        if (bodyKey.isNotEmpty()) store.setApiKey(bodyKey)
        JsonCodec.asMap(body["device"])?.let { rawDev ->
            runCatching { DeviceIdentity.recordFromMap(rawDev) }.getOrNull()?.let { rec ->
                synchronized(stateLock) { deviceState = rec }
            }
        }
        val bodyToken = (body["refresh_token"] ?: "").toString().trim()
        return authLock.withLock {
            val logged = synchronized(stateLock) { client != null && dashboard != null }
            if (logged) return sessionPayload()
            val token = bodyToken.ifEmpty { store.readRefreshToken() ?: "" }
            if (token.isEmpty()) {
                return linkedMapOf("ok" to true, "restored" to false, "reason" to "no_saved_token")
            }
            val prov = getProvider(token)
            try {
                val payload = completeUmaLogin(prov)
                payload["restored"] = true
                payload
            } catch (exc: Exception) {
                linkedMapOf("ok" to true, "restored" to false, "reason" to (exc.message ?: "restore failed"))
            }
        }
    }

    private fun forgetDeviceState() {
        synchronized(stateLock) { deviceState = null }
        Files.deleteIfExists(store.deviceFile)
    }

    private fun teardown(forgetCredentials: Boolean) = authLock.withLock {
        runner.stop()
        val oldC: UmaClient?
        val oldP: SteamTicketProvider?
        synchronized(stateLock) {
            oldC = client
            oldP = provider
            client = null
            provider = null
            rawAccountData = null
            dashboard = null
            lastQrUrl = ""
        }
        oldC?.close()
        oldP?.close()
        if (forgetCredentials) {
            store.clearCredentials(forgetApiKey = true)
            synchronized(stateLock) { deviceState = null }
        }
        runner.clearAccountData()
        syncedFinishedMarker = null
    }

    fun logout(): LinkedHashMap<String, Any?> {
        teardown(forgetCredentials = true)
        return linkedMapOf("ok" to true, "logged_in" to false)
    }

    fun setTurnDelay(body: Map<String, Any?>): LinkedHashMap<String, Any?> {
        val cur = store.loadSettings().turnDelay
        val disabled = JsonCodec.asBool(body["disabled"], false)
        val minV = JsonCodec.asDouble(body["min"], cur.restoreMin)
        val maxV = JsonCodec.asDouble(body["max"], cur.restoreMax)
        val saved = store.setTurnDelay(minV, maxV, disabled)
        synchronized(stateLock) { client?.let { applyTurnDelay(it, saved) } }
        return LinkedHashMap(saved.toMap()).apply {
            put("ok", true)
            put("turn_delay", saved.toMap())
        }
    }

    fun setBurnClocks(body: Map<String, Any?>): LinkedHashMap<String, Any?> {
        val enabled = JsonCodec.asBool(body["burn_clocks"], false)
        store.setBurnClocks(enabled)
        runner.setBurnClocks(enabled)
        return linkedMapOf("ok" to true, "burn_clocks" to enabled, "runner" to runner.snapshot())
    }

    fun setCmConfig(body: Map<String, Any?>): LinkedHashMap<String, Any?> {
        val settings = store.loadSettings()
        if (!AppConstants.CM_ENABLED) {
            val cur = LinkedHashMap(settings.cmConfig).apply { put("cm_mode", false) }
            return linkedMapOf("ok" to true, "cm_enabled" to false, "cm_config" to cur)
        }
        val patch = JsonCodec.asMap(body["cm_config"]) ?: body
        val normalized = store.setCmConfig(patch)
        return linkedMapOf("ok" to true, "cm_enabled" to true, "cm_config" to normalized)
    }

    fun startCareerRun(body: Map<String, Any?>): LinkedHashMap<String, Any?> = authLock.withLock {
        val (umaClient, cachedAcc) = synchronized(stateLock) {
            client to rawAccountData?.let { LinkedHashMap(it) }
        }
        if (umaClient == null) throw IllegalStateException("Not logged in")
        if (runner.running) {
            return linkedMapOf("ok" to true, "already_running" to true, "runner" to runner.snapshot())
        }
        val probeData = LinkedHashMap(StateStripper.unwrapData(umaClient.login(readInfo = false)))
        if (probeData.isEmpty()) throw IllegalStateException("Account probe returned no data")
        val light = JsonCodec.asMap(probeData["single_mode_chara_light"] ?: probeData["single_mode_chara"])
        val charaId = JsonCodec.asLong(light?.get("single_mode_chara_id"), 0L)
        if (light == null || charaId <= 0L) throw IllegalStateException("no active career (start one in-game)")
        val scen = JsonCodec.asInt(light["scenario_id"], 3)
        if (scen != 3) throw IllegalStateException("Career scenario $scen, not Grand Live (3).")
        if (cachedAcc?.get("trained_chara_array") != null && probeData["trained_chara_array"] == null) {
            probeData["trained_chara_array"] = cachedAcc["trained_chara_array"]
        }

        val settings = store.loadSettings()
        if (settings.apiKey.isEmpty()) throw BrainApiException("Add an API key first")
        val burn = JsonCodec.asBool(body["burn_clocks"], settings.burnClocks)
        val cmOptions = if (AppConstants.CM_ENABLED) {
            val rawCm = JsonCodec.asMap(body["cm_config"]) ?: settings.cmConfig
            StateStripper.resolveCmOptionsForAccount(rawCm, probeData)
        } else {
            null
        }
        val brain = BrainClient(settings.apiUrl, settings.apiKey, http)
        brain.onKeyRefresh = { rotatedKey ->
            runCatching { store.setApiKey(rotatedKey) }
        }
        applyTurnDelay(umaClient, settings.turnDelay)
        runner.start(umaClient, brain, burnClocks = burn, cmOptions = cmOptions, accountData = probeData)
        linkedMapOf("ok" to true, "runner" to runner.snapshot())
    }

    fun stopRunner(): LinkedHashMap<String, Any?> {
        runner.stop()
        return linkedMapOf("ok" to true, "runner" to runner.snapshot())
    }

    fun runnerStatus(): LinkedHashMap<String, Any?> {
        syncRunnerSettlement()
        val snap = runner.snapshot()
        return linkedMapOf("ok" to true, "runner" to snap, "account" to accountView(snap))
    }

    fun finalTurnExport(): LinkedHashMap<String, Any?> {
        val exp = runner.finalTurnExport() ?: throw IllegalArgumentException("No final-turn career state captured yet")
        @Suppress("UNCHECKED_CAST")
        val jsonObj = exp["json"] as Map<String, Any?>
        val chara = JsonCodec.asMap(jsonObj["chara_info"])
        val resolvedName = catalog.charaName(chara?.get("card_id")).takeUnless { it.startsWith("Unknown (") }
        exp["filename"] = UmaDumpExport.exportFilename(chara, resolvedName)
        return LinkedHashMap(exp).apply { put("ok", true) }
    }

    override fun close() {
        teardown(forgetCredentials = false)
    }

    private data class SessionSnapshotState(
        val loggedIn: Boolean,
        val brainOnline: Boolean,
        val brainHealth: LinkedHashMap<String, Any?>?,
        val rawAccount: LinkedHashMap<String, Any?>?,
    )

    companion object {
        private fun maskApiKey(apiKey: String): String {
            if (apiKey.isEmpty()) return ""
            if (apiKey.length <= 8) return "•".repeat(apiKey.length)
            return "${apiKey.take(6)}…${apiKey.takeLast(4)}"
        }

        private fun steamErrorPayload(exc: SteamTicketException): LinkedHashMap<String, Any?> {
            if (!exc.transport && exc.stage.startsWith("credentials")) {
                return linkedMapOf(
                    "ok" to false,
                    "error" to (exc.message ?: "Steam rejected login"),
                    "state" to (exc.safeReason ?: "credentials_rejected"),
                    "result_code" to exc.resultCode,
                    "retryable" to false,
                )
            }
            return linkedMapOf(
                "ok" to false,
                "error" to "steam_unavailable",
                "detail" to (exc.message ?: "steam_unavailable"),
                "state" to "steam_unavailable",
                "result_code" to exc.resultCode,
                "retryable" to exc.transport,
            )
        }
    }
}

class LocalHttpServer(
    private val engine: SweepyEngine,
    requestedPort: Int = 0,
) : Closeable {
    private val serverSocket = ServerSocket(requestedPort, 64, InetAddress.getByName("127.0.0.1"))
    val port: Int = serverSocket.localPort
    val url: String = "http://127.0.0.1:$port"

    @Volatile private var closed = false
    private val pool = Executors.newCachedThreadPool { r ->
        Thread(r, "sweepy-http-worker").apply { isDaemon = true }
    }
    private val acceptThread = Thread(
        {
            while (!closed && !serverSocket.isClosed) {
                val sock = try {
                    serverSocket.accept()
                } catch (_: Exception) {
                    break
                }
                pool.execute { handleConnection(sock) }
            }
        },
        "sweepy-http-accept",
    ).apply {
        isDaemon = true
        start()
    }

    private fun handleConnection(sock: Socket) {
        sock.use { s ->
            s.soTimeout = 15_000
            val input = BufferedInputStream(s.getInputStream())
            val out = s.getOutputStream()
            val req = readHttpRequest(input) ?: return
            val resp = dispatch(req)
            out.write(resp)
            out.flush()
        }
    }

    private data class HttpRequest(
        val method: String,
        val target: String,
        val headers: Map<String, String>,
        val body: ByteArray,
    )

    private fun readHttpRequest(input: BufferedInputStream): HttpRequest? {
        val headerBuf = ByteArrayOutputStream()
        var state = 0
        while (headerBuf.size() < 32 * 1024) {
            val b = input.read()
            if (b < 0) return if (headerBuf.size() == 0) null else throw EOFException("Truncated HTTP headers")
            headerBuf.write(b)
            state = when (state) {
                0 -> if (b == '\r'.code) 1 else 0
                1 -> if (b == '\n'.code) 2 else if (b == '\r'.code) 1 else 0
                2 -> if (b == '\r'.code) 3 else 0
                3 -> if (b == '\n'.code) break else 0
                else -> 0
            }
        }
        val lines = headerBuf.toByteArray().toString(Charsets.ISO_8859_1).split("\r\n")
        if (lines.isEmpty()) return null
        val first = lines[0].split(' ')
        if (first.size < 2) return null
        val method = first[0].uppercase()
        val target = first[1]
        val hdrs = LinkedHashMap<String, String>()
        for (line in lines.drop(1)) {
            if (line.isEmpty()) break
            val colon = line.indexOf(':')
            if (colon > 0) {
                hdrs[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
            }
        }
        if (hdrs.containsKey("transfer-encoding")) {
            return HttpRequest(method, target, hdrs, ByteArray(0))
        }
        val contentLength = hdrs["content-length"]?.toIntOrNull() ?: 0
        if (contentLength < 0 || contentLength > MAX_BODY_BYTES) {
            return HttpRequest(method, target, hdrs, ByteArray(0))
        }
        val body = ByteArray(contentLength)
        var read = 0
        while (read < contentLength) {
            val n = input.read(body, read, contentLength - read)
            if (n < 0) break
            read += n
        }
        return HttpRequest(method, target, hdrs, body.copyOf(read))
    }

    private fun validateLocalRequest(req: HttpRequest, isPost: Boolean): String? {
        val rawHost = req.headers["host"] ?: ""
        val cleanHost = if (rawHost.startsWith("[") && ']' in rawHost) {
            rawHost.substring(1, rawHost.indexOf(']')).lowercase()
        } else {
            rawHost.substringBeforeLast(':').lowercase()
        }
        if (cleanHost.isEmpty() || cleanHost !in ALLOWED_LOCAL_HOSTS) return "Forbidden Host header"
        if (isPost) {
            val origin = req.headers["origin"].orEmpty()
            if (origin.isNotEmpty() && !originIsLocal(origin)) return "Forbidden Origin header"
            val fetchSite = req.headers["sec-fetch-site"].orEmpty().lowercase()
            if (fetchSite.isNotEmpty() && fetchSite !in ALLOWED_FETCH_SITES) return "Cross-site request rejected"
        }
        return null
    }

    private fun originIsLocal(origin: String): Boolean = runCatching {
        val u = URI(origin)
        val h = u.host?.lowercase()?.trim('[', ']') ?: return false
        (u.scheme == "http" || u.scheme == "https") && h in ALLOWED_LOCAL_HOSTS
    }.getOrDefault(false)

    private fun dispatch(req: HttpRequest): ByteArray {
        val isPost = req.method == "POST"
        validateLocalRequest(req, isPost)?.let { reason ->
            return jsonResponse(403, mapOf("ok" to false, "error" to reason))
        }
        val qIdx = req.target.indexOf('?')
        val path = if (qIdx >= 0) req.target.substring(0, qIdx) else req.target
        val query = if (qIdx >= 0) parseQuery(req.target.substring(qIdx + 1)) else emptyMap()

        if (req.method == "GET") {
            val staticFile = when (path) {
                "/", "/index.html" -> "index.html" to "text/html; charset=utf-8"
                "/styles.css" -> "styles.css" to "text/css; charset=utf-8"
                "/app.js" -> "app.js" to "application/javascript; charset=utf-8"
                "/sweepy3.webp" -> "sweepy3.webp" to "image/webp"
                "/sweepy2.png", "/favicon.ico" -> "sweepy2.png" to "image/png"
                else -> null
            }
            if (staticFile != null) {
                val data = engine.assets.readBytes(staticFile.first)
                    ?: return jsonResponse(404, mapOf("ok" to false, "error" to "Not found"))
                val cache = if (staticFile.first.endsWith(".png") || staticFile.first.endsWith(".webp")) "public, max-age=300" else "no-store"
                return buildHttpResponse(200, "OK", staticFile.second, data, cacheControl = cache)
            }
            return try {
                when (path) {
                    "/api/session" -> jsonResponse(200, engine.sessionPayload(refresh = query["fresh"] == "1"))
                    "/api/career/runner" -> jsonResponse(200, engine.runnerStatus())
                    "/api/career/final-turn-export" -> {
                        val exp = engine.finalTurnExport()
                        if (query["download"] == "1") {
                            val safeName = (exp["filename"] ?: "umadump.json").toString().replace("\"", "").replace(";", "")
                            val bytes = JsonCodec.encodePretty(exp["json"]).toByteArray(Charsets.UTF_8)
                            buildHttpResponse(
                                200, "OK", "application/json; charset=utf-8", bytes,
                                extraHeaders = mapOf("Content-Disposition" to "attachment; filename=\"$safeName\""),
                            )
                        } else {
                            jsonResponse(200, exp)
                        }
                    }
                    else -> jsonResponse(404, mapOf("ok" to false, "error" to "Unknown route: $path"))
                }
            } catch (exc: BrainApiException) {
                jsonResponse(502, mapOf("ok" to false, "error" to (exc.message ?: "Brain error")))
            } catch (exc: Exception) {
                jsonResponse(400, mapOf("ok" to false, "error" to (exc.message ?: "Request failed")))
            }
        }

        if (isPost) {
            return try {
                if (req.headers.containsKey("transfer-encoding")) throw IllegalArgumentException("chunked bodies unsupported")
                val lenHeader = req.headers["content-length"]
                if (lenHeader != null && lenHeader.toIntOrNull() == null) throw IllegalArgumentException("bad Content-Length")
                if ((req.headers["content-length"]?.toIntOrNull() ?: 0) > MAX_BODY_BYTES) {
                    throw IllegalArgumentException("Request body exceeds 2 MiB limit")
                }
                val body = if (req.body.isEmpty()) {
                    emptyMap()
                } else {
                    val ct = req.headers["content-type"]?.substringBefore(';')?.trim()?.lowercase().orEmpty()
                    if (ct != "application/json") throw IllegalArgumentException("Content-Type is not application/json")
                    JsonCodec.decodeMap(req.body.toString(Charsets.UTF_8))
                }
                when (path) {
                    "/api/config/brain" -> jsonResponse(200, engine.configureBrain(body))
                    "/api/auth/qr/start" -> authPayloadResponse(engine.qrStart())
                    "/api/auth/qr/poll" -> authPayloadResponse(engine.qrPoll(body))
                    "/api/auth/credentials/start" -> authPayloadResponse(engine.credentialsStart(body))
                    "/api/auth/credentials/code" -> authPayloadResponse(engine.credentialsSubmitCode(body))
                    "/api/auth/credentials/poll" -> authPayloadResponse(engine.qrPoll(body))
                    "/api/auth/finalize" -> authPayloadResponse(engine.finalizeSteamLogin())
                    "/api/auth/restore" -> authPayloadResponse(engine.restoreSession(body))
                    "/api/logout" -> jsonResponse(200, engine.logout())
                    "/api/settings/turn-delay" -> jsonResponse(200, engine.setTurnDelay(body))
                    "/api/settings/cm" -> jsonResponse(200, engine.setCmConfig(body))
                    "/api/career/runner/burn_clocks" -> jsonResponse(200, engine.setBurnClocks(body))
                    "/api/career/run" -> jsonResponse(200, engine.startCareerRun(body))
                    "/api/career/runner/stop" -> jsonResponse(200, engine.stopRunner())
                    else -> jsonResponse(404, mapOf("ok" to false, "error" to "Unknown route: $path"))
                }
            } catch (exc: BrainApiException) {
                jsonResponse(502, mapOf("ok" to false, "online" to false, "error" to (exc.message ?: "Brain error")))
            } catch (exc: Exception) {
                jsonResponse(400, mapOf("ok" to false, "error" to (exc.message ?: "Request failed")))
            }
        }

        return jsonResponse(404, mapOf("ok" to false, "error" to "Unknown route: $path"))
    }

    private fun authPayloadResponse(payload: Map<String, Any?>): ByteArray {
        val status = when {
            payload["error"] == "steam_unavailable" -> 503
            payload["ok"] == false -> 400
            else -> 200
        }
        return jsonResponse(status, payload)
    }

    private fun jsonResponse(status: Int, payload: Any?): ByteArray {
        val reason = when (status) {
            200 -> "OK"
            400 -> "Bad Request"
            403 -> "Forbidden"
            404 -> "Not Found"
            502 -> "Bad Gateway"
            503 -> "Service Unavailable"
            else -> "Error"
        }
        return buildHttpResponse(
            status, reason, "application/json; charset=utf-8",
            JsonCodec.encode(payload).toByteArray(Charsets.UTF_8),
        )
    }

    private fun buildHttpResponse(
        status: Int,
        reason: String,
        contentType: String,
        body: ByteArray,
        cacheControl: String = "no-store",
        extraHeaders: Map<String, String> = emptyMap(),
    ): ByteArray {
        val hdr = StringBuilder()
        hdr.append("HTTP/1.1 ").append(status).append(' ').append(reason).append("\r\n")
        hdr.append("Server: sweepy\r\n")
        hdr.append("Connection: close\r\n")
        hdr.append("Content-Type: ").append(contentType).append("\r\n")
        hdr.append("Content-Length: ").append(body.size).append("\r\n")
        hdr.append("Cache-Control: ").append(cacheControl).append("\r\n")
        for ((k, v) in SECURITY_HEADERS) hdr.append(k).append(": ").append(v).append("\r\n")
        for ((k, v) in extraHeaders) hdr.append(k).append(": ").append(v).append("\r\n")
        hdr.append("\r\n")
        val hdrBytes = hdr.toString().toByteArray(Charsets.ISO_8859_1)
        return ByteArray(hdrBytes.size + body.size).also {
            System.arraycopy(hdrBytes, 0, it, 0, hdrBytes.size)
            System.arraycopy(body, 0, it, hdrBytes.size, body.size)
        }
    }

    override fun close() {
        closed = true
        runCatching { serverSocket.close() }
        runCatching { pool.shutdownNow() }
        runCatching { acceptThread.join(1000) }
    }

    companion object {
        private const val MAX_BODY_BYTES = 2 * 1024 * 1024
        private val ALLOWED_LOCAL_HOSTS = setOf("127.0.0.1", "localhost", "::1")
        private val ALLOWED_FETCH_SITES = setOf("same-origin", "none")
        private val SECURITY_HEADERS = linkedMapOf(
            "X-Content-Type-Options" to "nosniff",
            "X-Frame-Options" to "DENY",
            "Referrer-Policy" to "no-referrer",
            "Cross-Origin-Opener-Policy" to "same-origin",
            "Cross-Origin-Resource-Policy" to "same-origin",
            "Permissions-Policy" to "camera=(), microphone=(), geolocation=(), payment=()",
            "Content-Security-Policy" to
                "default-src 'self'; script-src 'self' 'unsafe-inline'; " +
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
                "img-src 'self' data:; connect-src 'self'; " +
                "font-src 'self' https://fonts.gstatic.com; object-src 'none'; " +
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )

        private fun parseQuery(qs: String): Map<String, String> {
            val out = LinkedHashMap<String, String>()
            for (part in qs.split('&')) {
                if (part.isEmpty()) continue
                val eq = part.indexOf('=')
                val k = URLDecoder.decode(if (eq >= 0) part.substring(0, eq) else part, Charsets.UTF_8)
                val v = if (eq >= 0) URLDecoder.decode(part.substring(eq + 1), Charsets.UTF_8) else ""
                out[k] = v
            }
            return out
        }
    }
}
