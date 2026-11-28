package top.mayano.sweepy.core

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.Closeable
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

class StateRecoveryException(
    message: String,
    val code: Int? = null,
    val endpoint: String? = null,
    val ambiguous: Boolean = false,
    val recovery: String? = null,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

data class RecoveryPolicy(
    val retryReadOnly: Boolean = false,
    val retryEndpoints: Set<String> = emptySet(),
    val ticketRefresh: Boolean = false,
    val recovery: String = "raise",
    val maxRetries: Int = 0,
)

class UmaClient(
    private val http: OkHttpClient,
    val udidStr: String,
    val deviceId: String,
    val deviceName: String,
    val graphicsDevice: String,
    val ipAddress: String,
    val platformOs: String,
    @Volatile var viewerId: Long,
    @Volatile var authKeyHex: String,
    @Volatile var steamId: String,
    @Volatile var steamTicket: String,
    @Volatile var appVer: String,
    @Volatile var resVer: String,
    val provider: SteamTicketProvider?,
    val timing: TimingDna?,
) : Closeable {
    private val callLock = ReentrantLock()
    private val rpcHttp: OkHttpClient = http.newBuilder()
        .callTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

    val unityVer = DEFAULT_UNITY_VER
    val locale = DeviceIdentity.DEFAULT_LOCALE

    @Volatile var sid: ByteArray = ByteArray(16)
    @Volatile var lastResponseHeader: ByteArray? = null
    @Volatile var currentScenarioId: Int? = null
    @Volatile var apiPrefix: String? = null
    private var lastRawCallMonoMs: Long = 0L

    var deviceState: DeviceStateRecord? = null
    val cachedLoadData = LinkedHashMap<String, Any?>()
    val tpInfo = LinkedHashMap<String, Any?>()
    val coinInfo = LinkedHashMap<String, Any?>()
    val itemMap = LinkedHashMap<Int, Int>()

    fun regenSid() = callLock.withLock {
        sid = UmaCrypto.makeSid(viewerId.toString(), udidStr)
    }

    fun setScenario(scenarioId: Int) {
        val prefix = SCENARIO_API_PREFIXES[scenarioId] ?: "single_mode_live"
        currentScenarioId = scenarioId
        apiPrefix = prefix
    }

    fun scenarioEndpoint(op: String): String {
        val prefix = apiPrefix ?: SCENARIO_API_PREFIXES[currentScenarioId ?: 3] ?: "single_mode_live"
        return "$prefix/${op.trimStart('/')}"
    }

    fun authBytes(): ByteArray =
        if (authKeyHex.isEmpty()) ByteArray(0) else UmaCrypto.hexToBytes(authKeyHex)

    private fun currentSteamCredentials(): Pair<String, String> {
        if (provider == null) return steamId to steamTicket
        try {
            val fresh = provider.ensureLease()
            if (fresh.isNotEmpty()) {
                steamId = provider.steamId
                steamTicket = fresh
                return steamId to steamTicket
            }
        } catch (_: SteamTicketException) {
            steamTicket = ""
        }
        try {
            val refreshed = provider.refresh()
            steamId = provider.steamId
            steamTicket = refreshed
            return steamId to steamTicket
        } catch (exc: SteamTicketException) {
            throw StateRecoveryException(
                "Steam ticket lease recovery failed: ${exc.message}",
                recovery = "refresh_ticket_and_reconcile",
                cause = exc,
            )
        }
    }

    fun buildCommon(viewerOverride: Long? = null): LinkedHashMap<String, Any?> {
        val (sId, sTicket) = currentSteamCredentials()
        val vid = viewerOverride ?: viewerId
        return linkedMapOf(
            "viewer_id" to vid,
            "device" to 4,
            "device_id" to deviceId,
            "device_name" to deviceName,
            "graphics_device_name" to graphicsDevice,
            "ip_address" to ipAddress,
            "platform_os_version" to platformOs,
            "carrier" to "",
            "keychain" to 0,
            "locale" to locale,
            "button_info" to "",
            "dmm_viewer_id" to null,
            "dmm_onetime_token" to null,
            "steam_id" to sId,
            "steam_session_ticket" to sTicket,
        )
    }

    fun refreshCachedAccountState(data: Map<String, Any?>?) {
        if (data == null) return
        cachedLoadData.putAll(data)
        JsonCodec.asMap(data["tp_info"])?.let { tp ->
            tpInfo.clear()
            tpInfo.putAll(tp)
        }
        JsonCodec.asMap(data["coin_info"])?.let { coin ->
            coinInfo.clear()
            coinInfo.putAll(coin)
        }
        val items = JsonCodec.asList(data["user_item"] ?: data["user_item_array"] ?: data["item_list"])
        if (items != null) {
            for (item in items) {
                val entry = JsonCodec.asMap(item) ?: continue
                val iid = JsonCodec.asLongOrNull(entry["item_id"])?.toInt() ?: continue
                val num = JsonCodec.asLongOrNull(entry["number"])?.toInt() ?: continue
                itemMap[iid] = num
            }
        }
    }

    private fun enforceCallFloor() {
        val nowMs = System.nanoTime() / 1_000_000L
        val waitMs = timing?.enforceFloorWaitMs(lastRawCallMonoMs, nowMs)
            ?: if (lastRawCallMonoMs > 0L) {
                val rem = ((TimingDna.HARD_CALL_FLOOR_SECONDS - (nowMs - lastRawCallMonoMs) / 1000.0) * 1000.0).toLong()
                if (rem > 0L) rem else 0L
            } else {
                0L
            }
        if (waitMs > 0L) Thread.sleep(waitMs)
        lastRawCallMonoMs = System.nanoTime() / 1_000_000L
    }

    fun probeResourceVersion(payload: Map<String, Any?>? = null): Map<String, Any?> = callLock.withLock {
        val savedSid = sid.copyOf()
        val savedViewer = viewerId
        val savedHeader = lastResponseHeader
        val probe = LinkedHashMap<String, Any?>().apply {
            put("attestation_type", 0)
            put("button_info", "")
            put("carrier", "")
            put("device_token", null)
            put("dmm_onetime_token", null)
            put("dmm_viewer_id", null)
            put("device", 4)
            put("device_id", deviceId)
            put("device_name", deviceName)
            put("graphics_device_name", graphicsDevice)
            put("ip_address", ipAddress)
            put("platform_os_version", platformOs)
            put("keychain", 0)
            put("locale", locale)
            if (payload != null) {
                for (k in listOf(
                    "attestation_type", "button_info", "carrier", "device_token", "dmm_onetime_token",
                    "dmm_viewer_id", "device", "device_id", "device_name", "graphics_device_name",
                    "ip_address", "platform_os_version", "keychain", "locale", "steam_id", "steam_session_ticket"
                )) {
                    if (payload.containsKey(k)) put(k, payload[k])
                }
            }
            put("viewer_id", 0)
        }
        try {
            sid = UmaCrypto.makeSid("0", udidStr)
            val res = call(
                PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT,
                probe,
                anonymous = true,
                versionProbe = true,
                appVersionRetryBudget = 1,
                resourceVersionRetryBudget = 0,
            )
            extractResourceVersion(res)?.let { rv -> resVer = rv }
            res
        } finally {
            sid = savedSid
            viewerId = savedViewer
            lastResponseHeader = savedHeader
        }
    }

    private fun refreshAppVersion(hint: String? = null) {
        if (hint != null && hint != appVer && APP_VER_RE.matches(hint.trim())) {
            appVer = hint.trim()
            return
        }
        val (ok, resolved) = lookupAppleAppVersion(http, forceRefresh = true)
        if (ok) {
            appVer = resolved
            return
        }
        if (hint != null && APP_VER_RE.matches(hint.trim())) {
            appVer = hint.trim()
            return
        }
        throw StateRecoveryException("App-version heal lookup failed")
    }

    private fun refreshResourceVersion(payload: Map<String, Any?>, hint: String? = null) {
        val validHint = hint?.trim()?.takeIf { RES_VER_RE.matches(it) && (it.toLongOrNull() ?: 0L) > 0L }
        if (validHint != null && validHint != resVer) {
            resVer = validHint
            return
        }
        val probeRes = try {
            probeResourceVersion(payload)
        } catch (exc: Exception) {
            if (validHint != null) {
                resVer = validHint
                return
            }
            throw StateRecoveryException("Resource-version heal failed", cause = exc)
        }
        val refreshed = extractResourceVersion(probeRes)
        if (refreshed != null) {
            resVer = refreshed
        } else if (validHint != null) {
            resVer = validHint
        } else {
            throw StateRecoveryException("Resource-version heal: no valid version")
        }
    }

    fun call(
        ep: String,
        args: Map<String, Any?> = emptyMap(),
        retry208: Int = 6,
        retry205: Int = 3,
        transportRetries: Int? = null,
        ticketRefreshBudget: Int = 1,
        payloadOverride: Map<String, Any?>? = null,
        appVersionRetryBudget: Int = 1,
        resourceVersionRetryBudget: Int = 1,
        versionProbe: Boolean = false,
        anonymous: Boolean = false,
        authOverride: ByteArray? = null,
        viewerHeaderOverride: String? = null,
        skipCommon: Boolean = false,
    ): LinkedHashMap<String, Any?> = callLock.withLock {
        val cleanEp = ep.trim()
        if (!API_ENDPOINT_RE.matches(cleanEp)) {
            throw StateRecoveryException("Invalid API endpoint: $cleanEp")
        }
        val apiUrl = BASE_URL + cleanEp
        enforceCallFloor()

        val payload = if (payloadOverride != null) {
            LinkedHashMap(payloadOverride)
        } else {
            LinkedHashMap<String, Any?>(args).apply {
                if (!anonymous && !skipCommon) putAll(buildCommon())
                if (!anonymous && cleanEp.endsWith("/race_out") && get("button_info").let { it == null || it == "" }) {
                    val scen = currentScenarioId ?: 3
                    put("button_info", timing?.makeRaceOutButtonInfo(viewerId, scen)
                        ?: TimingDna.makeRaceOutFallback(viewerId, scen))
                }
            }
        }

        val stateChanging = cleanEp.trimEnd('/') !in READ_ONLY_RETRY_ENDPOINTS
        val maxAttempts = (transportRetries?.plus(1)) ?: if (stateChanging) 1 else 4
        val authMaterial = when {
            anonymous -> ByteArray(0)
            authOverride != null -> authOverride
            else -> authBytes()
        }
        val udidRaw = UmaCrypto.getRawUdid(udidStr)

        lastResponseHeader = null
        var httpStatus = 0
        var respBytes = ByteArray(0)
        for (attempt in 0 until maxAttempts) {
            val wireBody = UmaCrypto.pack(sid, udidRaw, authMaterial, payload, udidStr)
            val reqBuilder = Request.Builder()
                .url(apiUrl)
                .header("User-Agent", "UnityPlayer/$unityVer (UnityWebRequest/1.0, libcurl/8.10.1-DEV)")
                .header("X-Unity-Version", unityVer)
                .header("Accept", "*/*")
                .header("SID", UmaCrypto.bytesToHex(sid))
                .header("Device", "4")
                .header("Device-SubType", "1")
                .header("APP-VER", appVer)
                .header("RES-VER", resVer)
                .post(wireBody.toRequestBody(MSGPACK_MEDIA))
            if (viewerHeaderOverride != null) {
                if (viewerHeaderOverride.isNotEmpty()) reqBuilder.header("ViewerID", viewerHeaderOverride)
            } else if (!anonymous) {
                reqBuilder.header("ViewerID", viewerId.toString())
            }

            try {
                rpcHttp.newCall(reqBuilder.build()).execute().use { r ->
                    httpStatus = r.code
                    respBytes = r.body.bytes()
                }
                break
            } catch (exc: Exception) {
                if (attempt < maxAttempts - 1) {
                    val waitMs = minOf(10_000L, (1000L + attempt * 2000L))
                    Thread.sleep(waitMs)
                    continue
                }
                throw StateRecoveryException(
                    "Transport error on $cleanEp: ${exc.message}",
                    endpoint = cleanEp,
                    ambiguous = stateChanging,
                    recovery = if (stateChanging) "reconcile" else "retry_read_only",
                    cause = exc,
                )
            }
        }

        if (httpStatus != 200) {
            val preview = respBytes.toString(Charsets.UTF_8).take(500)
            val (appIssue0, resIssue0) = versionIssue(preview)
            val appIssue = appIssue0 || httpStatus == 202
            val resIssue = resIssue0 || httpStatus == 202
            if ((appIssue && appVersionRetryBudget > 0) || (resIssue && !versionProbe && resourceVersionRetryBudget > 0)) {
                var nextApp = appVersionRetryBudget
                var nextRes = resourceVersionRetryBudget
                if (appIssue && appVersionRetryBudget > 0) {
                    refreshAppVersion()
                    nextApp--
                }
                if (resIssue && !versionProbe && resourceVersionRetryBudget > 0) {
                    refreshResourceVersion(payload)
                    nextRes--
                }
                return call(
                    cleanEp, args, retry208, retry205, transportRetries, ticketRefreshBudget, payload,
                    nextApp, nextRes, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon
                )
            }
            throw StateRecoveryException(
                "HTTP $httpStatus on $cleanEp: $preview",
                code = httpStatus,
                endpoint = cleanEp,
                ambiguous = stateChanging,
                recovery = if (stateChanging) "reconcile" else "raise",
            )
        }

        val (decodedAny, protoHdr) = UmaCrypto.unpack(respBytes, udidStr)
        lastResponseHeader = protoHdr
        @Suppress("UNCHECKED_CAST")
        val res = (decodedAny as? LinkedHashMap<String, Any?>)
            ?: (decodedAny as? Map<*, *>)?.let { LinkedHashMap<String, Any?>().apply { it.forEach { (k, v) -> if (k != null) put(k.toString(), v) } } }
            ?: throw StateRecoveryException("Decoded UMA response on $cleanEp is not a map", endpoint = cleanEp)

        extractResponseSid(res)?.let { rsid ->
            sid = when (rsid) {
                is ByteArray -> UmaCrypto.nextSid(rsid)
                else -> UmaCrypto.nextSid(rsid.toString())
            }
        }

        val rc = extractResponseCode(res)
        val dh = JsonCodec.asMap(res["data_headers"]) ?: emptyMap()
        val data = JsonCodec.asMap(res["data"]) ?: emptyMap()

        if (cleanEp in setOf(PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT, "tool/start_session", "load/index") && rc == 1) {
            extractResourceVersion(res)?.let { resVer = it }
        }
        if (data.isNotEmpty()) {
            refreshCachedAccountState(data)
            JsonCodec.asMap(data["chara_info"])?.let { ci ->
                val sc = JsonCodec.asInt(ci["scenario_id"], -1)
                if (sc in SCENARIO_API_PREFIXES) setScenario(sc)
            }
        }

        if (rc == 204 && appVersionRetryBudget > 0) {
            refreshAppVersion(hint = extractAppVersionHint(res))
            return call(
                cleanEp, args, retry208, retry205, transportRetries, ticketRefreshBudget, payload,
                appVersionRetryBudget - 1, resourceVersionRetryBudget, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon
            )
        }
        if (rc == 214 && !versionProbe && resourceVersionRetryBudget > 0) {
            refreshResourceVersion(payload, hint = extractResourceVersion(res))
            return call(
                cleanEp, args, retry208, retry205, transportRetries, ticketRefreshBudget, payload,
                appVersionRetryBudget, resourceVersionRetryBudget - 1, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon
            )
        }

        val (appIssue0, resIssue0) = versionIssue(res)
        val appIssue = appIssue0 || rc == 202
        val resIssue = resIssue0 || rc == 202
        if ((appIssue && appVersionRetryBudget > 0) || (resIssue && !versionProbe && resourceVersionRetryBudget > 0)) {
            var nextApp = appVersionRetryBudget
            var nextRes = resourceVersionRetryBudget
            if (appIssue && appVersionRetryBudget > 0) {
                refreshAppVersion()
                nextApp--
            }
            if (resIssue && !versionProbe && resourceVersionRetryBudget > 0) {
                refreshResourceVersion(payload)
                nextRes--
            }
            return call(
                cleanEp, args, retry208, retry205, transportRetries, ticketRefreshBudget, payload,
                nextApp, nextRes, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon
            )
        }

        if (rc in setOf(394, 501) && ticketRefreshBudget > 0 && provider != null) {
            val refreshed = try {
                provider.refresh()
            } catch (exc: Exception) {
                throw StateRecoveryException("Steam session ticket refresh failed on $cleanEp: ${exc.message}", code = rc, endpoint = cleanEp, recovery = "refresh_ticket_and_reconcile", cause = exc)
            }
            steamTicket = refreshed
            val retryPayload = LinkedHashMap(payload)
            if (retryPayload.containsKey("steam_session_ticket")) {
                retryPayload["steam_id"] = steamId
                retryPayload["steam_session_ticket"] = refreshed
            }
            if (retryPayload.containsKey("authentication_token")) {
                retryPayload["authentication_token"] = refreshed
            }
            return call(
                cleanEp, args, retry208, retry205, transportRetries, ticketRefreshBudget - 1, retryPayload,
                appVersionRetryBudget, resourceVersionRetryBudget, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon
            )
        }

        if (rc == null) throw StateRecoveryException("Missing or contradictory result_code on $cleanEp", endpoint = cleanEp)

        if (rc == 709) {
            extractViewerId(res)?.toLongOrNull()?.let { nv ->
                if (nv > 0L && nv != viewerId) {
                    viewerId = nv
                    regenSid()
                }
            }
            throw StateRecoveryException("Viewer identity mismatch (rc=709) on $cleanEp", code = 709, endpoint = cleanEp, recovery = "replace_identity_and_rebootstrap")
        }

        if (rc != 1) {
            val eid = JsonCodec.asLongOrNull(payload["event_id"]) ?: 0L
            if (rc == 205 && cleanEp.endsWith("/check_event") && eid == 0L) return res
            if (rc == 205 && retry205 > 0 && !stateChanging) {
                Thread.sleep(166L)
                return call(cleanEp, args, retry208, retry205 - 1, transportRetries, ticketRefreshBudget, payload, appVersionRetryBudget, resourceVersionRetryBudget, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon)
            }
            if (rc == 208 && retry208 > 0 && (cleanEp in GLOBAL_208_RETRY_ENDPOINTS || !stateChanging)) {
                if (retry208 < 6) Thread.sleep(800L)
                return call(cleanEp, args, retry208 - 1, retry205, transportRetries, ticketRefreshBudget, payload, appVersionRetryBudget, resourceVersionRetryBudget, versionProbe, anonymous, authOverride, viewerHeaderOverride, skipCommon)
            }
            val errMsg = (dh["error_message"] ?: data["error_message"] ?: "").toString()
            val policy = RECOVERY_POLICIES[rc]
            throw StateRecoveryException(
                "UMA API error rc=$rc on $cleanEp" + if (errMsg.isNotEmpty()) " ($errMsg)" else "",
                code = rc,
                endpoint = cleanEp,
                recovery = policy?.recovery ?: "reconcile",
            )
        }
        return res
    }

    fun readInfo(): LinkedHashMap<String, Any?> = call(
        "read_info/index",
        mapOf(
            "add_home_story_data_array" to emptyList<Any?>(),
            "add_short_episode_data_array" to emptyList<Any?>(),
            "add_home_poster_data_array" to emptyList<Any?>(),
            "add_tutorial_guide_data_array" to emptyList<Any?>(),
            "add_released_episode_data_array" to emptyList<Any?>(),
            "add_talk_gallery_data_array" to emptyList<Any?>(),
            "add_home_banner_data_array" to emptyList<Any?>(),
        ),
    )

    fun login(maxRetries: Int = 3, readInfo: Boolean = true): LinkedHashMap<String, Any?> {
        if (viewerId <= 0L || authKeyHex.isEmpty()) {
            throw HeadlessAuthException("Login needs viewer_id and auth_key")
        }
        for (attempt in 0..maxRetries) {
            try {
                regenSid()
                call("tool/start_session", mapOf("attestation_type" to 0, "device_token" to null))
                val res = call("load/index", mapOf("adid" to ""))
                refreshCachedAccountState(JsonCodec.asMap(res["data"]))
                if (readInfo) {
                    try {
                        readInfo()
                    } catch (exc: StateRecoveryException) {
                        if (exc.code != 102 || exc.endpoint != "read_info/index") throw exc
                    }
                }
                return res
            } catch (exc: StateRecoveryException) {
                if (exc.code in setOf(202, 709) && attempt < maxRetries) {
                    Thread.sleep(850L)
                    continue
                }
                throw exc
            }
        }
        throw StateRecoveryException("Login retries exhausted", endpoint = "load/index")
    }

    fun loadCareer(scenarioId: Int? = null): LinkedHashMap<String, Any?> {
        if (scenarioId != null) setScenario(scenarioId)
        else if (currentScenarioId == null) setScenario(3)
        return call(scenarioEndpoint("load"), emptyMap())
    }

    fun gainSkills(items: List<Map<String, Any?>>, currentTurn: Int): LinkedHashMap<String, Any?> {
        val norm = items.map {
            mapOf(
                "skill_id" to JsonCodec.asInt(it["skill_id"]),
                "level" to JsonCodec.asInt(it["level"] ?: it["skill_level"], 1),
            )
        }
        return call(scenarioEndpoint("gain_skills"), mapOf("gain_skill_info_array" to norm, "current_turn" to currentTurn))
    }

    override fun close() {
        provider?.close()
    }

    companion object {
        const val BASE_URL = "https://api.games.umamusume.com/umamusume/"
        const val APP_LOOKUP_URL = "https://itunes.apple.com/lookup?id=6480433538"
        const val DEFAULT_APP_VER = "1.34.0"
        const val DEFAULT_UNITY_VER = "2022.3.62f2"
        const val PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT = "tool/get_pre_download_resource_version"

        val SCENARIO_API_PREFIXES = mapOf(
            1 to "single_mode",
            2 to "single_mode_team",
            3 to "single_mode_live",
            4 to "single_mode_free",
        )

        private val MSGPACK_MEDIA = "application/x-msgpack".toMediaType()
        private val API_ENDPOINT_RE = Regex("^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
        private val APP_VER_RE = Regex("^[0-9]+(?:\\.[0-9]+)+$")
        private val RES_VER_RE = Regex("^[0-9]{1,32}$")
        private val NON_ALNUM = Regex("[^a-z0-9]")

        val READ_ONLY_RETRY_ENDPOINTS = setOf(
            "load/index", "read_info/index",
            "single_mode/load", "single_mode_team/load", "single_mode_live/load", "single_mode_free/load",
            "single_mode_live/get_choice_reward", "single_mode/get_choice_reward",
            "pre_single_mode/index", "account/get_by_social_account", "tool/pre_signup",
            PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT,
        )
        val GLOBAL_208_RETRY_ENDPOINTS = setOf("single_mode_live/master_square", "single_mode_free/master_square")
        val RECOVERY_POLICIES = mapOf(
            205 to RecoveryPolicy(retryReadOnly = true, recovery = "reconcile", maxRetries = 3),
            208 to RecoveryPolicy(retryReadOnly = true, retryEndpoints = GLOBAL_208_RETRY_ENDPOINTS, recovery = "reconcile", maxRetries = 6),
            217 to RecoveryPolicy(recovery = "rebootstrap_and_reconcile"),
            394 to RecoveryPolicy(retryReadOnly = true, ticketRefresh = true, recovery = "refresh_ticket_and_reconcile", maxRetries = 1),
            501 to RecoveryPolicy(retryReadOnly = true, ticketRefresh = true, recovery = "refresh_ticket_and_reconcile", maxRetries = 1),
            709 to RecoveryPolicy(recovery = "replace_identity_and_rebootstrap"),
        )

        @Volatile private var cachedAppVer: String? = null

        fun lookupAppleAppVersion(http: OkHttpClient, forceRefresh: Boolean = false): Pair<Boolean, String> {
            if (!forceRefresh) cachedAppVer?.let { return true to it }
            val client = http.newBuilder().callTimeout(5, TimeUnit.SECONDS).build()
            val req = Request.Builder().url(APP_LOOKUP_URL).get().build()
            return try {
                client.newCall(req).execute().use { resp ->
                    if (resp.code != 200) return false to (cachedAppVer ?: DEFAULT_APP_VER)
                    val parsed = JsonCodec.decodeMap(resp.body.string())
                    if (JsonCodec.asInt(parsed["resultCount"]) != 1) return false to (cachedAppVer ?: DEFAULT_APP_VER)
                    val results = JsonCodec.asList(parsed["results"]) ?: return false to (cachedAppVer ?: DEFAULT_APP_VER)
                    val entry = JsonCodec.asMap(results.firstOrNull()) ?: return false to (cachedAppVer ?: DEFAULT_APP_VER)
                    if (JsonCodec.asLong(entry["trackId"]) != 6480433538L || entry["bundleId"] != "com.cygames.umamusume") {
                        return false to (cachedAppVer ?: DEFAULT_APP_VER)
                    }
                    val ver = (entry["version"] as? String)?.trim()
                    if (ver != null && ver.length <= 64 && APP_VER_RE.matches(ver)) {
                        cachedAppVer = ver
                        true to ver
                    } else {
                        false to (cachedAppVer ?: DEFAULT_APP_VER)
                    }
                }
            } catch (_: Exception) {
                false to (cachedAppVer ?: DEFAULT_APP_VER)
            }
        }

        private fun extractResponseSid(res: Map<String, Any?>): Any? {
            for (c in listOf(JsonCodec.asMap(res["data_headers"]), res)) {
                if (c == null) continue
                for ((k, v) in c) {
                    if (k.equals("sid", ignoreCase = true) && v != null) {
                        if (v is ByteArray && v.isNotEmpty()) return v
                        val s = v.toString().trim()
                        if (s.isNotEmpty()) return s
                    }
                }
            }
            return null
        }

        private fun extractResponseCode(res: Map<String, Any?>): Int? {
            val dh = JsonCodec.asMap(res["data_headers"])
            val nested = dh?.entries?.firstOrNull { it.key.equals("result_code", ignoreCase = true) }?.value
            val vals = mutableSetOf<Int>()
            for (c in listOf(res["response_code"], res["result_code"], nested)) {
                if (c == null || c is Boolean) continue
                val n = JsonCodec.asLongOrNull(c) ?: return null
                vals.add(n.toInt())
            }
            return if (vals.size == 1) vals.first() else null
        }

        private fun extractResourceVersion(value: Any?, depth: Int = 0): String? {
            if (depth > 4) return null
            when (value) {
                is Map<*, *> -> {
                    for ((k, v) in value) {
                        val norm = NON_ALNUM.replace((k ?: "").toString().lowercase(), "")
                        if (norm in setOf("resourceversion", "resversion", "resver")) {
                            val rv = v?.toString()?.trim() ?: return null
                            return rv.takeIf { RES_VER_RE.matches(it) && (it.toLongOrNull() ?: 0L) > 0L }
                        }
                    }
                    for (sub in listOf("data_headers", "data", "result", "payload")) {
                        if (value.containsKey(sub)) extractResourceVersion(value[sub], depth + 1)?.let { return it }
                    }
                }
                is List<*> -> {
                    for (item in value.take(32)) extractResourceVersion(item, depth + 1)?.let { return it }
                }
            }
            return null
        }

        private fun extractAppVersionHint(value: Any?, depth: Int = 0): String? {
            if (depth > 4 || value !is Map<*, *>) return null
            val targets = setOf("appver", "appversion", "requiredappver", "requiredappversion", "requiredversion", "clientversion")
            for ((k, v) in value) {
                val norm = NON_ALNUM.replace((k ?: "").toString().lowercase(), "")
                if (norm in targets) {
                    val s = (v as? String)?.trim()
                    if (s != null && APP_VER_RE.matches(s)) return s
                }
            }
            for (sub in listOf("data_headers", "data", "result", "payload")) {
                if (value.containsKey(sub)) extractAppVersionHint(value[sub], depth + 1)?.let { return it }
            }
            return null
        }

        private fun extractViewerId(res: Map<String, Any?>): String? {
            val keys = listOf("viewer_id", "ViewerId", "viewerId", "newViewerId", "new_viewer_id")
            for (c in listOf(res, JsonCodec.asMap(res["data_headers"]), JsonCodec.asMap(res["data"]))) {
                if (c == null) continue
                for (k in keys) {
                    val v = JsonCodec.asLongOrNull(c[k]) ?: continue
                    if (v > 0L) return v.toString()
                }
            }
            return null
        }

        private fun extractServerAuth(client: UmaClient, res: Map<String, Any?>): ByteArray? =
            UmaCrypto.issuedAuthFromHeader(client.lastResponseHeader) ?: UmaCrypto.authFromResponse(res)

        private fun versionIssue(value: Any?, depth: Int = 0): Pair<Boolean, Boolean> {
            if (depth > 4 || value == null) return false to false
            var app = false
            var res = false
            val terms = listOf("version mismatch", "version invalid", "unsupported version", "version outdated")
            when (value) {
                is Map<*, *> -> for ((k, v) in value) {
                    val norm = NON_ALNUM.replace((k ?: "").toString().lowercase(), "")
                    if (norm in setOf("invalidappver", "invalidappversion", "unsupportedappver", "unsupportedappversion")) app = true
                    else if (norm in setOf("invalidresver", "invalidresourceversion", "unsupportedresver", "unsupportedresourceversion")) res = true
                    else if (norm in setOf("versionmismatch", "versionerror")) { app = true; res = true }
                    else if (v is String) {
                        val low = v.lowercase()
                        if ("version" in low && terms.any { it in low }) { app = true; res = true }
                    }
                    val (sa, sr) = versionIssue(v, depth + 1)
                    app = app || sa
                    res = res || sr
                }
                is List<*> -> for (item in value.take(32)) {
                    val (sa, sr) = versionIssue(item, depth + 1)
                    app = app || sa
                    res = res || sr
                }
                is String -> {
                    val low = value.lowercase()
                    if (terms.any { it in low }) { app = true; res = true }
                }
            }
            return app to res
        }

        fun bootstrapHeadlessAuth(
            store: RuntimeStore,
            http: OkHttpClient,
            provider: SteamTicketProvider,
            deviceState: DeviceStateRecord? = null,
            persistDevice: Boolean = true,
        ): Pair<UmaClient, LinkedHashMap<String, Any?>> {
            val ticket = try {
                provider.ensureLease()
            } catch (exc: SteamTicketException) {
                throw HeadlessAuthException("Steam ticket failed during bootstrap: ${exc.message}", cause = exc)
            }
            return bootstrapWithTicket(
                store = store,
                http = http,
                steamId = provider.steamId,
                ticket = ticket,
                provider = provider,
                deviceState = deviceState,
                persistDevice = persistDevice,
            )
        }

        internal fun bootstrapWithTicket(
            store: RuntimeStore,
            http: OkHttpClient,
            steamId: String,
            ticket: String,
            provider: SteamTicketProvider? = null,
            deviceState: DeviceStateRecord? = null,
            persistDevice: Boolean = true,
        ): Pair<UmaClient, LinkedHashMap<String, Any?>> {
            val steamIdHash = DeviceIdentity.computeSteamIdHash(steamId)
            val stable = deviceState?.takeIf { it.steamIdHash == steamIdHash }
                ?: DeviceIdentity.readDeviceState(store.deviceFile, expectedSteamIdHash = steamIdHash)

            val timing = TimingDna(store.timingSeedFile)
            val freshIdentity = stable == null

            val udid = stable?.udid ?: UUID.randomUUID().toString()
            val device = DeviceIdentity.runtimeDeviceFields(udid, stable?.deviceId, store)
            val resVer = stable?.resourceVersion ?: DeviceIdentity.DEFAULT_RES_VER
            val needsProbe = stable == null || !stable.resourceVersionKnown
            val stableViewer = stable?.viewerId
            val stableAuth = if (stable == null) ByteArray(0) else UmaCrypto.hexToBytes(stable.authKeyHex)

            val (_, appVer) = lookupAppleAppVersion(http)
            val client = UmaClient(
                http = http,
                udidStr = udid,
                deviceId = device["device_id"].toString(),
                deviceName = device["device_name"].toString(),
                graphicsDevice = device["graphics_device_name"].toString(),
                ipAddress = device["ip_address"].toString(),
                platformOs = device["platform_os_version"].toString(),
                viewerId = stableViewer?.toLong() ?: 0L,
                authKeyHex = if (stableAuth.isNotEmpty()) UmaCrypto.bytesToHex(stableAuth) else "",
                steamId = steamId,
                steamTicket = ticket,
                appVer = appVer,
                resVer = resVer,
                provider = provider,
                timing = timing,
            )

            var succeeded = false
            try {
                if (needsProbe) {
                    runCatching {
                        client.probeResourceVersion(LinkedHashMap(device).apply {
                            put("steam_id", client.steamId)
                            put("steam_session_ticket", client.steamTicket)
                        })
                    }
                }

                var issuedViewer: String
                var issuedAuth: ByteArray

                if (freshIdentity) {
                    client.sid = UmaCrypto.makeSid("0", udid)
                    val socialViewer = try {
                        val socialRes = client.call(
                            "account/get_by_social_account",
                            mapOf(
                                "openid" to client.steamId,
                                "openid_type" to 5,
                                "authentication_token" to client.steamTicket,
                                "not_return_error" to true,
                                "steam_id" to client.steamId,
                                "steam_session_ticket" to client.steamTicket,
                            ),
                            authOverride = ByteArray(0),
                            viewerHeaderOverride = "0",
                            skipCommon = true,
                        )
                        extractViewerId(socialRes)
                    } catch (_: StateRecoveryException) {
                        null
                    }
                    if (socialViewer != null) {
                        client.sid = UmaCrypto.makeSid(socialViewer, udid)
                        val startPayload = client.buildCommon(viewerOverride = 0L).apply {
                            remove("viewer_id")
                            put("attestation_type", 0)
                            put("device_token", null)
                        }
                        val startRes = client.call(
                            "tool/start_session",
                            startPayload,
                            authOverride = ByteArray(0),
                            viewerHeaderOverride = socialViewer,
                            skipCommon = true,
                        )
                        requireNonTutorialStart(startRes)
                        issuedAuth = extractServerAuth(client, startRes)?.takeIf { it.size == 48 }
                            ?: throw HeadlessAuthException("start_session: no 164-byte auth_key", code = 1, endpoint = "tool/start_session")
                        issuedViewer = extractViewerId(startRes) ?: socialViewer
                    } else {
                        client.sid = UmaCrypto.makeSid("0", udid)
                        val prePayload = linkedMapOf<String, Any?>(
                            "attestation_type" to 0,
                            "button_info" to "",
                            "carrier" to "",
                            "device_token" to null,
                            "dmm_onetime_token" to null,
                            "dmm_viewer_id" to null,
                        ).apply {
                            putAll(device)
                            put("keychain", 0)
                            put("steam_id", client.steamId)
                            put("steam_session_ticket", client.steamTicket)
                            put("viewer_id", 0)
                        }
                        val preRes = try {
                            client.call(
                                "tool/pre_signup",
                                prePayload,
                                authOverride = ByteArray(0),
                                viewerHeaderOverride = "",
                                skipCommon = true,
                            )
                        } catch (exc: StateRecoveryException) {
                            throw HeadlessAuthException("pre_signup failed: ${exc.message}", code = exc.code, endpoint = "tool/pre_signup", cause = exc)
                        }
                        val preData = JsonCodec.asMap(preRes["data"])
                        if (preData == null || preData["enable_steam_account"] != true) {
                            throw HeadlessAuthException("pre_signup: enrollment not enabled", code = 1, endpoint = "tool/pre_signup")
                        }
                        var country = ""
                        for (entry in JsonCodec.asList(preData["country_list"]) ?: emptyList()) {
                            val cand = when (entry) {
                                is Map<*, *> -> (entry["country"] ?: "").toString().trim()
                                else -> (entry ?: "").toString().trim()
                            }
                            if (cand.isNotEmpty()) {
                                country = cand
                                break
                            }
                        }
                        if (country.isEmpty()) {
                            throw HeadlessAuthException("pre_signup: country_list empty", code = 1, endpoint = "tool/pre_signup")
                        }
                        client.sid = UmaCrypto.makeSid("0", udid)
                        val signupPayload = linkedMapOf<String, Any?>(
                            "credential" to "",
                            "error_code" to 0,
                            "error_message" to "",
                            "attestation_type" to 0,
                            "optin_user_birth" to 199001,
                            "dma_state" to 0,
                            "country" to country,
                            "viewer_id" to 0,
                        ).apply {
                            putAll(device)
                            put("steam_id", client.steamId)
                            put("steam_session_ticket", client.steamTicket)
                        }
                        val signupRes = try {
                            client.call(
                                "tool/signup",
                                signupPayload,
                                authOverride = ByteArray(0),
                                viewerHeaderOverride = "0",
                                skipCommon = true,
                            )
                        } catch (exc: StateRecoveryException) {
                            throw HeadlessAuthException("signup failed: ${exc.message}", code = exc.code, endpoint = "tool/signup", cause = exc)
                        }
                        val signupViewer = extractViewerId(signupRes)
                        val signupAuth = extractServerAuth(client, signupRes)?.takeIf { it.size == 48 }
                        if (signupViewer == null || signupAuth == null) {
                            throw HeadlessAuthException("signup: no viewer_id or 48-byte auth_key", code = 1, endpoint = "tool/signup")
                        }
                        client.viewerId = signupViewer.toLong()
                        client.authKeyHex = UmaCrypto.bytesToHex(signupAuth)
                        client.sid = UmaCrypto.makeSid(signupViewer, udid)
                        val startRes = client.call(
                            "tool/start_session",
                            mapOf("attestation_type" to 0, "device_token" to null),
                        )
                        requireNonTutorialStart(startRes)
                        val rotated = extractServerAuth(client, startRes)?.takeIf { it.size == 48 }
                        issuedAuth = rotated ?: signupAuth
                        issuedViewer = extractViewerId(startRes) ?: signupViewer
                    }
                } else {
                    client.viewerId = stableViewer!!.toLong()
                    client.authKeyHex = UmaCrypto.bytesToHex(stableAuth)
                    client.regenSid()
                    val startRes = client.call("tool/start_session", mapOf("attestation_type" to 0, "device_token" to null))
                    val returnedVid = extractViewerId(startRes)
                    val rotatedAuth = extractServerAuth(client, startRes)
                    if (returnedVid != null && returnedVid != stableViewer) {
                        if (rotatedAuth == null || rotatedAuth.size != 48) {
                            throw HeadlessAuthException("viewer_id changed without fresh auth_key", code = 1, endpoint = "tool/start_session")
                        }
                        issuedViewer = returnedVid
                        issuedAuth = rotatedAuth
                    } else {
                        issuedViewer = returnedVid ?: stableViewer
                        issuedAuth = rotatedAuth ?: stableAuth
                    }
                }

                client.viewerId = issuedViewer.toLong()
                client.authKeyHex = UmaCrypto.bytesToHex(issuedAuth)

                var rebootstrapDone = false
                lateinit var loadRes: LinkedHashMap<String, Any?>
                while (true) {
                    try {
                        loadRes = client.call("load/index", mapOf("adid" to ""))
                        break
                    } catch (exc: StateRecoveryException) {
                        if (!rebootstrapDone && exc.code == 709 && !freshIdentity && provider != null) {
                            rebootstrapDone = true
                            client.steamTicket = provider.refresh()
                            client.regenSid()
                            val s2 = client.call("tool/start_session", mapOf("attestation_type" to 0, "device_token" to null))
                            requireNonTutorialStart(s2)
                            val a2 = extractServerAuth(client, s2)?.takeIf { it.size == 48 && !it.contentEquals(issuedAuth) }
                                ?: throw HeadlessAuthException("709 rebootstrap: no fresh 48-byte auth_key", code = 709)
                            issuedViewer = extractViewerId(s2) ?: client.viewerId.toString()
                            issuedAuth = a2
                            client.viewerId = issuedViewer.toLong()
                            client.authKeyHex = UmaCrypto.bytesToHex(issuedAuth)
                            continue
                        }
                        if (!rebootstrapDone && exc.code == 217) {
                            rebootstrapDone = true
                            client.regenSid()
                            val s2 = client.call("tool/start_session", mapOf("attestation_type" to 0, "device_token" to null))
                            extractServerAuth(client, s2)?.takeIf { it.size == 48 }?.let {
                                issuedAuth = it
                                client.authKeyHex = UmaCrypto.bytesToHex(it)
                            }
                            continue
                        }
                        throw HeadlessAuthException("load/index failed: ${exc.message}", code = exc.code, endpoint = "load/index", cause = exc)
                    }
                }

                val loadAuth = extractServerAuth(client, loadRes)
                val loadVid = extractViewerId(loadRes)
                if (loadVid != null && loadVid != issuedViewer) {
                    if (loadAuth == null || loadAuth.size != 48) {
                        throw HeadlessAuthException("viewer_id changed without fresh auth_key", code = 1, endpoint = "load/index")
                    }
                    issuedViewer = loadVid
                    issuedAuth = loadAuth
                } else if (loadAuth != null && loadAuth.size == 48) {
                    issuedAuth = loadAuth
                }

                client.viewerId = issuedViewer.toLong()
                client.authKeyHex = UmaCrypto.bytesToHex(issuedAuth)
                client.refreshCachedAccountState(JsonCodec.asMap(loadRes["data"]))

                val record = DeviceStateRecord(
                    udid = udid,
                    deviceId = client.deviceId,
                    viewerId = issuedViewer,
                    authKeyHex = UmaCrypto.bytesToHex(issuedAuth),
                    steamIdHash = steamIdHash,
                    resourceVersion = client.resVer,
                )
                if (persistDevice) {
                    DeviceIdentity.writeDeviceState(store.deviceFile, record)
                }
                client.deviceState = record
                succeeded = true
                return client to loadRes
            } finally {
                if (!succeeded) client.close()
            }
        }

        private fun requireNonTutorialStart(res: Map<String, Any?>) {
            val data = JsonCodec.asMap(res["data"])
                ?: throw HeadlessAuthException("start_session: no is_tutorial", code = 1, endpoint = "tool/start_session")
            val isTut = data["is_tutorial"] as? Boolean
                ?: throw HeadlessAuthException("start_session: is_tutorial not boolean", code = 1, endpoint = "tool/start_session")
            if (isTut) {
                throw HeadlessAuthException("start_session: tutorial not initialized", code = 1, endpoint = "tool/start_session")
            }
        }
    }
}

private fun TimingDna.Companion.makeRaceOutFallback(viewerId: Long, scenarioId: Int): String =
    JsonCodec.encode(
        linkedMapOf(
            "ViewerId" to viewerId,
            "DeviceId" to 4,
            "ScenarioId" to scenarioId,
            "ClickPosX" to 9910000,
            "ClickPosY" to 1440000,
            "ClickServerTime" to (System.currentTimeMillis() / 1000L - 3L),
        )
    )
