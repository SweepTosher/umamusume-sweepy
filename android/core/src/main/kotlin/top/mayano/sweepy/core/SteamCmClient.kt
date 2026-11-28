package top.mayano.sweepy.core

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.io.Closeable
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.spec.RSAPublicKeySpec
import java.util.Base64
import java.util.Collections
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingDeque
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.zip.CRC32
import javax.crypto.Cipher

class SteamTicketException(
    message: String,
    val stage: String = "unknown",
    val resultCode: Int? = null,
    val safeReason: String? = null,
    val transport: Boolean = false,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

private class CmWebSocketSession(
    http: OkHttpClient,
    wsUrl: String,
) : Closeable {
    val gcTokens = LinkedBlockingDeque<ByteArray>()
    @Volatile var steamId64: Long = 0L
    @Volatile var clientSessionId: Int = 0
    @Volatile var loggedOn: Boolean = false
    @Volatile private var closed = false
    @Volatile private var readerError: Throwable? = null

    private val jobWaiters = ConcurrentHashMap<Long, CompletableFuture<ProtoWire.SteamPacket>>()
    private val emsgWaiters = ConcurrentHashMap<Int, CopyOnWriteArrayList<CompletableFuture<ProtoWire.SteamPacket>>>()
    private val scheduler = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "steam-cm-hb").apply { isDaemon = true }
    }
    @Volatile private var hbFuture: ScheduledFuture<*>? = null

    private val openFuture = CompletableFuture<Unit>()
    private val ws: WebSocket

    init {
        val req = Request.Builder().url(wsUrl).build()
        ws = http.newWebSocket(
            req,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    openFuture.complete(Unit)
                }

                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    runCatching { dispatch(bytes.toByteArray()) }.onFailure { failAll(it) }
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    failAll(SteamTicketException("Steam CM closing ($code)", stage = "connect", transport = true))
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    openFuture.completeExceptionally(t)
                    failAll(t)
                }
            },
        )
        try {
            openFuture.get(15, TimeUnit.SECONDS)
        } catch (exc: Exception) {
            close()
            throw exc
        }
    }

    val alive: Boolean get() = !closed && readerError == null

    private fun failAll(err: Throwable) {
        readerError = err
        val sentinel = ProtoWire.SteamPacket(-1, ProtoWire.ProtoBufHeader(eresult = 0), ByteArray(0))
        for ((_, fut) in jobWaiters) fut.complete(sentinel)
        for ((_, list) in emsgWaiters) {
            for (fut in list) fut.complete(sentinel)
        }
    }

    private fun dispatch(rawPacket: ByteArray) {
        val pkt = try {
            ProtoWire.unpackCmPacket(rawPacket)
        } catch (_: UnsupportedPacketException) {
            return
        }
        if (pkt.emsg == ProtoWire.EMSG_MULTI) {
            for (inner in ProtoWire.unpackMulti(pkt.body)) {
                runCatching { dispatch(inner) }
            }
            return
        }
        if (pkt.emsg == ProtoWire.EMSG_CLIENT_LOGON_RESPONSE) {
            pkt.header.clientSessionid?.let { clientSessionId = it }
            pkt.header.steamid?.let { if (it != 0L) steamId64 = it }
        }
        if (pkt.emsg == ProtoWire.EMSG_CLIENT_GAME_CONNECT_TOKENS) {
            for (tok in ProtoWire.decodeGameConnectTokens(pkt.body)) {
                if (tok.isNotEmpty()) gcTokens.add(tok)
            }
        }
        pkt.header.jobidTarget?.let { target ->
            if (target != 0L && target != SteamTicketProvider.NO_JOB_ID) {
                jobWaiters[target]?.complete(pkt)
            }
        }
        emsgWaiters[pkt.emsg]?.forEach { it.complete(pkt) }
    }

    fun startHeartbeat(intervalSeconds: Int) {
        val sec = maxOf(5, intervalSeconds).toLong()
        if (hbFuture != null) return
        hbFuture = scheduler.scheduleAtFixedRate(
            {
                if (!alive) return@scheduleAtFixedRate
                if (!loggedOn) return@scheduleAtFixedRate
                runCatching {
                    sendProto(ProtoWire.EMSG_CLIENT_HEARTBEAT, ProtoWire.encodeClientHeartBeat(), authenticated = true)
                }.onFailure { failAll(it) }
            },
            sec, sec, TimeUnit.SECONDS,
        )
    }

    fun sendProto(
        emsg: Int,
        body: ByteArray,
        header: ProtoWire.ProtoBufHeader? = null,
        authenticated: Boolean = false,
    ) {
        if (!alive) throw SteamTicketException("Steam CM session is closed", stage = "connect", transport = true)
        val hdr = header ?: if (authenticated) {
            ProtoWire.ProtoBufHeader(steamid = steamId64, clientSessionid = clientSessionId)
        } else {
            ProtoWire.ProtoBufHeader(steamid = 0L, clientSessionid = 0)
        }
        val bytes = ProtoWire.packCmPacket(emsg, hdr, body)
        if (!ws.send(bytes.toByteString())) {
            val ex = SteamTicketException("Steam CM send failed", stage = "connect", transport = true)
            failAll(ex)
            throw ex
        }
    }

    fun sendAndWaitEmsg(
        sendEmsg: Int,
        body: ByteArray,
        expectEmsg: Int,
        header: ProtoWire.ProtoBufHeader? = null,
        authenticated: Boolean = false,
        timeoutSec: Long = 15L,
        stage: String = "unknown",
    ): ProtoWire.SteamPacket {
        val fut = CompletableFuture<ProtoWire.SteamPacket>()
        val list = emsgWaiters.getOrPut(expectEmsg) { CopyOnWriteArrayList() }
        list.add(fut)
        try {
            sendProto(sendEmsg, body, header = header, authenticated = authenticated)
            val got = try {
                fut.get(timeoutSec, TimeUnit.SECONDS)
            } catch (exc: Exception) {
                throw SteamTicketException(
                    "Timed out waiting for Steam EMsg $expectEmsg",
                    stage = stage,
                    safeReason = "timeout",
                    cause = exc,
                )
            }
            if (got.emsg == -1) {
                throw SteamTicketException(
                    "CM closed while waiting for EMsg $expectEmsg",
                    stage = stage,
                    transport = true,
                    cause = readerError,
                )
            }
            return got
        } finally {
            list.remove(fut)
        }
    }

    fun callServiceNonAuthed(
        methodName: String,
        body: ByteArray,
        timeoutSec: Long = 15L,
        stage: String = "unknown",
    ): ProtoWire.SteamPacket {
        val jobId = 1L + (SteamTicketProvider.rng.nextLong() ushr 2)
        val fut = CompletableFuture<ProtoWire.SteamPacket>()
        jobWaiters[jobId] = fut
        try {
            val hdr = ProtoWire.ProtoBufHeader(
                steamid = 0L,
                clientSessionid = 0,
                jobidSource = jobId,
                targetJobName = methodName,
                realm = 1,
            )
            sendProto(ProtoWire.EMSG_SERVICE_METHOD_CALL_FROM_CLIENT_NON_AUTHED, body, header = hdr, authenticated = false)
            val got = try {
                fut.get(timeoutSec, TimeUnit.SECONDS)
            } catch (exc: Exception) {
                throw SteamTicketException("Steam service call timed out ($methodName)", stage = stage, safeReason = "timeout", cause = exc)
            }
            if (got.emsg == -1) {
                throw SteamTicketException("Steam CM disconnected during $methodName", stage = stage, safeReason = "timeout", transport = true, cause = readerError)
            }
            if (got.emsg != ProtoWire.EMSG_SERVICE_METHOD_RESPONSE) {
                throw SteamTicketException("Unexpected EMsg ${got.emsg} for $methodName", stage = stage, safeReason = "service_rejected")
            }
            val er = got.header.eresult ?: 0
            if (er != SteamTicketProvider.ERESULT_OK) {
                val detail = got.header.errorMessage?.takeIf { it.isNotBlank() }
                throw SteamTicketException(
                    detail ?: SteamTicketProvider.friendlyEresultMessage(methodName, er),
                    stage = stage,
                    resultCode = er,
                    safeReason = "service_rejected",
                )
            }
            return got
        } finally {
            jobWaiters.remove(jobId)
        }
    }

    fun waitForGcToken(timeoutSec: Long = 20L): ByteArray {
        val tok = gcTokens.poll(timeoutSec, TimeUnit.SECONDS)
            ?: if (!alive) {
                throw SteamTicketException("CM closed before game-connect token", stage = "connect_token", cause = readerError)
            } else {
                throw SteamTicketException("timeout waiting for ClientGameConnectTokens", stage = "connect_token", safeReason = "timeout")
            }
        return tok
    }

    override fun close() {
        closed = true
        failAll(SteamTicketException("Steam CM session closed", stage = "connect"))
        runCatching { hbFuture?.cancel(true) }
        runCatching { scheduler.shutdownNow() }
        runCatching { ws.close(1000, "bye") }
    }
}

class SteamTicketProvider(
    private val store: RuntimeStore,
    private val http: OkHttpClient,
    token: String? = null,
    private val f2pRetryDelayMs: Long = 1500L,
) : Closeable {
    private val lock = Any()
    private var memoryToken: String = ""
    private var authCm: CmWebSocketSession? = null
    private var liveSession: CmWebSocketSession? = null

    private var qrClientId: Long = 0L
    private var qrRequestId: ByteArray = ByteArray(0)
    private var qrChallengeUrl: String = ""
    private var qrIntervalSec: Double = 5.0
    private var hasQrState: Boolean = false
    private var credSteamId: Long = 0L
    private var credAllowedConfirmations: List<ProtoWire.AllowedConfirmation> = emptyList()

    @Volatile var steamId: String = ""
        private set
    @Volatile var steamSessionTicket: String = ""
        private set

    private var boundSteamIdHash: String? = null
    private var appOwnershipTicket: ByteArray = ByteArray(0)
    private var connectNano: Long = 0L
    private var ticketSeq: Int = 0
    private var authListSeq: Int = 0
    private var lastServerSeq: Int = 0
    private val steamPipe: Int = 1 + rng.nextInt(1_000_000)

    init {
        if (!token.isNullOrBlank()) {
            val cleaned = token.trim()
            decodeSteamRefreshJwt(cleaned)
            memoryToken = cleaned
        }
    }

    fun hasRefreshToken(): Boolean = synchronized(lock) {
        memoryToken.isNotEmpty() || store.readRefreshToken()?.let {
            decodeSteamRefreshJwt(it)
            true
        } ?: false
    }

    fun currentToken(): String = synchronized(lock) {
        if (memoryToken.isNotEmpty()) return memoryToken
        store.readRefreshToken() ?: throw SteamTicketException("No Steam refresh token", stage = "token")
    }

    private fun resolveToken(): Pair<String, String> {
        val tok = currentToken()
        return tok to decodeSteamRefreshJwt(tok)
    }

    private fun adoptToken(candidate: String, stage: String): String {
        val cleaned = candidate.trim()
        val sid = decodeSteamRefreshJwt(cleaned)
        if (cleaned.toByteArray(Charsets.UTF_8).size > MAX_REFRESH_TOKEN_BYTES) {
            throw SteamTicketException("Refresh token size invalid", stage = stage, safeReason = "invalid_token")
        }
        memoryToken = cleaned
        return sid
    }

    fun persistRefreshToken() = synchronized(lock) {
        val tok = memoryToken.trim()
        if (tok.isNotEmpty()) {
            runCatching { store.saveRefreshToken(tok) }
        }
    }

    private fun discoverCmUrls(): List<String> {
        val req = Request.Builder().url(CM_DISCOVERY_URL).get().build()
        val bodyText = try {
            http.newCall(req).execute().use { resp ->
                if (resp.code != 200) throw SteamTicketException("CM directory HTTP ${resp.code}", stage = "connect", transport = true)
                resp.body.string()
            }
        } catch (exc: SteamTicketException) {
            throw exc
        } catch (exc: Exception) {
            throw SteamTicketException("Steam WebSocket CM discovery failed: ${exc.message}", stage = "connect", transport = true, cause = exc)
        }
        val parsed = runCatching { JsonCodec.decodeMap(bodyText) }
            .getOrElse { throw SteamTicketException("Bad CM directory JSON", stage = "connect") }
        val responseObj = JsonCodec.asMap(parsed["response"])
            ?: throw SteamTicketException("bad CM directory payload", stage = "connect")
        val serverList = JsonCodec.asList(responseObj["serverlist"])
            ?: throw SteamTicketException("Steam CM directory returned no serverlist", stage = "connect")

        val candidates = mutableListOf<Pair<Double, String>>()
        for (item in serverList) {
            val row = JsonCodec.asMap(item) ?: continue
            val realm = (row["realm"] ?: "steamglobal").toString()
            val cmType = (row["type"] ?: "websockets").toString()
            if (realm != "steamglobal" || cmType != "websockets") continue
            val ep = (row["endpoint"] ?: "").toString()
            val colon = ep.lastIndexOf(':')
            if (colon <= 0) continue
            val host = ep.substring(0, colon).trim()
            val port = ep.substring(colon + 1).toIntOrNull() ?: continue
            if (host.isEmpty() || port !in 1..65535) continue
            val load = JsonCodec.asDouble(row["wtd_load"] ?: row["load"], 100.0)
            candidates.add(load to "wss://$host:$port/cmsocket/")
        }
        val ordered = candidates.sortedBy { it.first }.map { it.second }.distinct()
        if (ordered.isEmpty()) throw SteamTicketException("no usable CM endpoints", stage = "connect")
        return ordered
    }

    private fun connectCmHello(stage: String, startOffset: Int = 0): CmWebSocketSession {
        val urls = discoverCmUrls()
        val shift = ((startOffset % urls.size) + urls.size) % urls.size
        val ordered = if (shift == 0) urls else urls.drop(shift) + urls.take(shift)
        var lastErr: Throwable? = null
        for (wsUrl in ordered.take(6)) {
            var sess: CmWebSocketSession? = null
            try {
                sess = CmWebSocketSession(http, wsUrl)
                sess.sendProto(ProtoWire.EMSG_CLIENT_HELLO, ProtoWire.encodeClientHello(), authenticated = false)
                return sess
            } catch (exc: Throwable) {
                lastErr = exc
                sess?.close()
            }
        }
        throw SteamTicketException("Unable to connect to any Steam CM (${lastErr?.message})", stage = stage, transport = true, cause = lastErr)
    }

    private fun closeAuthCm() {
        authCm?.close()
        authCm = null
    }

    private fun ensureAuthCm(stage: String, attempt: Int = 0): CmWebSocketSession {
        authCm?.takeIf { it.alive }?.let { return it }
        closeAuthCm()
        return connectCmHello(stage, startOffset = attempt).also { authCm = it }
    }

    private fun callNonAuthedRetry(method: String, body: ByteArray, stage: String): ProtoWire.SteamPacket {
        var lastExc: SteamTicketException? = null
        for (attempt in 0..2) {
            val cm = ensureAuthCm(stage, attempt)
            try {
                return cm.callServiceNonAuthed(method, body, stage = stage)
            } catch (exc: SteamTicketException) {
                lastExc = exc
                val msg = (exc.message ?: "").lowercase()
                val retryable = exc.resultCode == ERESULT_TRY_ANOTHER_CM ||
                    exc.safeReason == "timeout" ||
                    exc.transport ||
                    "session is closed" in msg ||
                    "connection closed" in msg ||
                    "disconnected" in msg
                closeAuthCm()
                if (!retryable || attempt >= 2) throw exc
            }
        }
        throw lastExc!!
    }

    fun startQrSession(): Map<String, Any?> = synchronized(lock) {
        hasQrState = false
        credSteamId = 0L
        credAllowedConfirmations = emptyList()
        closeAuthCm()
        val respPkt = callNonAuthedRetry(METHOD_BEGIN_QR, ProtoWire.encodeBeginQrRequest(), stage = "qr_bootstrap")
        val resp = ProtoWire.BeginQrResponse.decode(respPkt.body)
        val url = resp.challengeUrl.trim()
        if (resp.clientId == 0L || resp.requestId.isEmpty() || !url.startsWith("https://s.team/q/")) {
            throw SteamTicketException("bad QR challenge", stage = "qr_bootstrap", safeReason = "invalid_challenge")
        }
        val iv = if (resp.interval > 0f) resp.interval.toDouble() else 5.0
        qrClientId = resp.clientId
        qrRequestId = resp.requestId
        qrChallengeUrl = url
        qrIntervalSec = iv
        hasQrState = true
        linkedMapOf(
            "client_id" to resp.clientId,
            "challenge_url" to url,
            "interval" to iv,
        )
    }

    fun startCredentialsSession(username: String, password: String): Map<String, Any?> = synchronized(lock) {
        val cleanUser = username.trim()
        require(cleanUser.isNotEmpty() && password.isNotEmpty()) { "Enter both Steam username and password" }

        hasQrState = false
        credSteamId = 0L
        credAllowedConfirmations = emptyList()
        closeAuthCm()

        val rsaPkt = callNonAuthedRetry(
            METHOD_GET_RSA_KEY,
            ProtoWire.encodeGetPasswordRsaKeyRequest(cleanUser),
            stage = "credentials_rsa",
        )
        val rsaKey = ProtoWire.PasswordRsaKeyResponse.decode(rsaPkt.body)
        if (rsaKey.modHex.isEmpty() || rsaKey.expHex.isEmpty() || rsaKey.timestamp == 0L) {
            throw SteamTicketException("Steam returned invalid RSA key", stage = "credentials_rsa")
        }

        val encrypted = encryptPasswordRsa(password, rsaKey.modHex, rsaKey.expHex)
        val credPkt = callNonAuthedRetry(
            METHOD_BEGIN_CREDENTIALS,
            ProtoWire.encodeBeginCredentialsRequest(
                accountName = cleanUser,
                encryptedPassword = encrypted,
                encryptionTimestamp = rsaKey.timestamp,
            ),
            stage = "credentials_login",
        )
        val resp = ProtoWire.BeginCredentialsResponse.decode(credPkt.body)
        if (resp.clientId == 0L || resp.requestId.isEmpty() || resp.steamId == 0L) {
            val extra = resp.extendedErrorMessage.takeIf { it.isNotBlank() }
            throw SteamTicketException(
                extra ?: "Steam rejected username or password",
                stage = "credentials_login",
            )
        }

        val iv = if (resp.interval > 0f) resp.interval.toDouble() else 3.0
        qrClientId = resp.clientId
        qrRequestId = resp.requestId
        qrChallengeUrl = ""
        qrIntervalSec = iv
        credSteamId = resp.steamId
        credAllowedConfirmations = resp.allowedConfirmations
        hasQrState = true

        val types = resp.allowedConfirmations.map { it.confirmationType }
        if (GUARD_NONE in types) {
            val polled = pollQrSession()
            if (polled["status"] == "approved") return polled
        }

        val guardNames = resp.allowedConfirmations.mapNotNull { guardSlug(it.confirmationType) }.distinct()
        val hint = resp.allowedConfirmations
            .firstOrNull { it.associatedMessage.isNotBlank() }
            ?.associatedMessage
            .orEmpty()

        linkedMapOf(
            "status" to "guard_required",
            "guard_types" to guardNames,
            "hint" to hint,
            "interval" to iv,
            "steam_id" to java.lang.Long.toUnsignedString(resp.steamId),
        )
    }

    fun submitSteamGuardCode(code: String, codeTypeOverride: Int? = null): Map<String, Any?> = synchronized(lock) {
        if (!hasQrState || credSteamId == 0L) {
            throw SteamTicketException("Steam login session expired — sign in again", stage = "credentials_guard", resultCode = ERESULT_EXPIRED)
        }
        val cleanCode = code.trim().uppercase()
        require(cleanCode.isNotEmpty()) { "Enter your Steam Guard code" }

        val targetType = codeTypeOverride ?: when {
            credAllowedConfirmations.any { it.confirmationType == GUARD_DEVICE_CODE } -> GUARD_DEVICE_CODE
            credAllowedConfirmations.any { it.confirmationType == GUARD_EMAIL_CODE } -> GUARD_EMAIL_CODE
            else -> GUARD_DEVICE_CODE
        }

        callNonAuthedRetry(
            METHOD_UPDATE_GUARD_CODE,
            ProtoWire.encodeUpdateSteamGuardCodeRequest(qrClientId, credSteamId, cleanCode, targetType),
            stage = "credentials_guard",
        )
        pollQrSession()
    }

    fun pollQrSession(): Map<String, Any?> = synchronized(lock) {
        if (!hasQrState) {
            return linkedMapOf("status" to "expired", "challenge_url" to null, "steam_id" to null, "interval" to null)
        }
        val isQr = qrChallengeUrl.isNotEmpty()
        val respPkt = try {
            callNonAuthedRetry(
                METHOD_POLL_STATUS,
                ProtoWire.encodePollStatusRequest(qrClientId, qrRequestId),
                stage = if (isQr) "qr_bootstrap" else "credentials_poll",
            )
        } catch (exc: SteamTicketException) {
            if (exc.resultCode == ERESULT_EXPIRED) {
                hasQrState = false
                credSteamId = 0L
                credAllowedConfirmations = emptyList()
                closeAuthCm()
                return linkedMapOf("status" to "expired", "challenge_url" to null, "steam_id" to null)
            }
            throw exc
        }
        val status = ProtoWire.PollStatusResponse.decode(respPkt.body)
        if (status.newClientId != 0L) qrClientId = status.newClientId
        val newUrl = status.newChallengeUrl.trim()
        if (newUrl.isNotEmpty()) {
            if (!newUrl.startsWith("https://s.team/q/")) {
                throw SteamTicketException("bad QR replacement URL", stage = "qr_bootstrap", safeReason = "invalid_challenge")
            }
            qrChallengeUrl = newUrl
        }
        val candidate = status.refreshToken.trim()
        if (candidate.isNotEmpty()) {
            val sid = adoptToken(candidate, if (isQr) "qr_bootstrap" else "credentials_poll")
            hasQrState = false
            credSteamId = 0L
            credAllowedConfirmations = emptyList()
            closeAuthCm()
            return linkedMapOf("status" to "approved", "challenge_url" to null, "steam_id" to sid, "interval" to null)
        }
        linkedMapOf(
            "status" to "pending",
            "challenge_url" to qrChallengeUrl.ifEmpty { null },
            "steam_id" to null,
            "interval" to qrIntervalSec,
            "had_remote_interaction" to status.hadRemoteInteraction,
        )
    }

    private fun openAuthenticatedCm(token: String, expectedSteamId: String): CmWebSocketSession {
        val parsedSid = java.lang.Long.parseUnsignedLong(expectedSteamId)
        var lastExc: Throwable? = null
        for (attempt in 0..2) {
            val cm = connectCmHello("connect", startOffset = attempt)
            try {
                val hdr = ProtoWire.ProtoBufHeader(
                    steamid = parsedSid,
                    clientSessionid = 0,
                    jobidSource = NO_JOB_ID,
                    jobidTarget = NO_JOB_ID,
                )
                val respPkt = cm.sendAndWaitEmsg(
                    ProtoWire.EMSG_CLIENT_LOGON,
                    ProtoWire.encodeClientLogon(token, expectedSteamId),
                    ProtoWire.EMSG_CLIENT_LOGON_RESPONSE,
                    header = hdr,
                    authenticated = false,
                    timeoutSec = 30L,
                    stage = "logon",
                )
                val logon = ProtoWire.LogonResponse.decode(respPkt.body)
                if (logon.eresult != ERESULT_OK) {
                    val msg = if (logon.eresult == 84) {
                        "Steam rate-limited sign-in (eresult=84) — wait a few minutes before retrying"
                    } else {
                        "Steam ClientLogon failed (eresult=${logon.eresult})"
                    }
                    throw SteamTicketException(
                        msg,
                        stage = "logon",
                        resultCode = logon.eresult,
                    )
                }
                val hdrSid = respPkt.header.steamid
                if (hdrSid != null && hdrSid != 0L && java.lang.Long.toUnsignedString(hdrSid) != expectedSteamId) {
                    throw SteamTicketException("Steam CM logged on with unexpected SteamID64", stage = "logon")
                }
                cm.steamId64 = parsedSid
                cm.loggedOn = true
                cm.startHeartbeat(if (logon.heartbeatSeconds > 0) logon.heartbeatSeconds else 15)
                connectNano = System.nanoTime()
                authListSeq = 0
                lastServerSeq = 0
                ticketSeq = 0
                appOwnershipTicket = fetchOwnershipTicket(cm)
                return cm
            } catch (t: Throwable) {
                cm.close()
                lastExc = t
                val ste = t as? SteamTicketException
                val retryable = ste != null && (
                    ste.resultCode == ERESULT_TRY_ANOTHER_CM ||
                        ste.safeReason == "timeout" ||
                        ste.transport
                    )
                if (!retryable || attempt >= 2) throw t
            }
        }
        throw lastExc!!
    }

    private fun fetchOwnershipTicket(cm: CmWebSocketSession): ByteArray {
        val reqBody = ProtoWire.encodeGetAppOwnershipTicket(APP_ID)
        val resp = ProtoWire.OwnershipTicketResponse.decode(
            cm.sendAndWaitEmsg(
                ProtoWire.EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET,
                reqBody,
                ProtoWire.EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE,
                authenticated = true,
                stage = "ownership_ticket",
            ).body
        )
        if (resp.eresult == ERESULT_OK && resp.ticket.isNotEmpty()) return resp.ticket

        val freeBytes = cm.sendAndWaitEmsg(
            ProtoWire.EMSG_CLIENT_REQUEST_FREE_LICENSE,
            ProtoWire.encodeRequestFreeLicense(APP_ID),
            ProtoWire.EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE,
            authenticated = true,
            stage = "ownership_ticket",
        ).body
        val freeEr = ProtoWire.decodeRequestFreeLicenseResponseEresult(freeBytes)
        if (freeEr != ERESULT_OK) {
            throw SteamTicketException("RequestFreeLicense failed (eresult=$freeEr)", stage = "ownership_ticket", resultCode = freeEr)
        }
        if (f2pRetryDelayMs > 0) Thread.sleep(f2pRetryDelayMs)
        val retryResp = ProtoWire.OwnershipTicketResponse.decode(
            cm.sendAndWaitEmsg(
                ProtoWire.EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET,
                reqBody,
                ProtoWire.EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE,
                authenticated = true,
                stage = "ownership_ticket",
            ).body
        )
        if (retryResp.eresult != ERESULT_OK || retryResp.ticket.isEmpty()) {
            throw SteamTicketException("GetAppOwnershipTicket failed (eresult=${retryResp.eresult})", stage = "ownership_ticket", resultCode = retryResp.eresult)
        }
        return retryResp.ticket
    }

    private fun ensureLiveCm(expectedHash: String? = null): CmWebSocketSession {
        val (tok, sid) = resolveToken()
        val actualHash = DeviceIdentity.computeSteamIdHash(sid)
        if (expectedHash != null && actualHash != expectedHash.trim().lowercase()) {
            throw SteamTicketException("account != expected SteamID hash", stage = "token")
        }
        if (boundSteamIdHash != null && actualHash != boundSteamIdHash) {
            throw SteamTicketException("token changed accounts", stage = "lease")
        }
        liveSession?.takeIf { it.alive && it.loggedOn && appOwnershipTicket.isNotEmpty() }?.let { return it }
        steamSessionTicket = ""
        liveSession?.close()
        liveSession = null
        val cm = openAuthenticatedCm(tok, sid)
        liveSession = cm
        steamId = sid
        boundSteamIdHash = actualHash
        return cm
    }

    private fun mintFromLiveCm(cm0: CmWebSocketSession): String {
        var cm = cm0
        val gcToken = try {
            cm.waitForGcToken(20L)
        } catch (_: SteamTicketException) {
            cm.close()
            liveSession = null
            cm = ensureLiveCm(boundSteamIdHash)
            cm.waitForGcToken(20L)
        }
        ticketSeq += 1
        authListSeq += 1
        val elapsedMs = maxOf(0, ((System.nanoTime() - connectNano) / 1_000_000L).toInt())
        val nonce = ByteArray(8).also { rng.nextBytes(it) }
        val authTicket = buildWebapiAuthTicket(gcToken, ticketSeq, elapsedMs, nonce)
        val crc = CRC32().apply { update(authTicket) }.value.toInt()

        val ackBytes = cm.sendAndWaitEmsg(
            ProtoWire.EMSG_CLIENT_AUTH_LIST,
            ProtoWire.encodeAuthList(
                tokensLeft = cm.gcTokens.size,
                lastReqSeq = maxOf(0, authListSeq - 1),
                lastServerSeq = lastServerSeq,
                ticketCrc = crc,
                authTicket = authTicket,
                appId = APP_ID,
                hSteamPipe = steamPipe,
                serverSecret = SERVER_SECRET,
                msgSeq = authListSeq,
            ),
            ProtoWire.EMSG_CLIENT_AUTH_LIST_ACK,
            authenticated = true,
            stage = "auth_register",
        ).body
        val ack = ProtoWire.AuthListAck.decode(ackBytes)
        val crcUnsigned = crc.toLong() and 0xFFFFFFFFL
        if (crcUnsigned !in ack.ticketCrcs) {
            throw SteamTicketException("AuthListAck CRC mismatch", stage = "auth_register")
        }
        lastServerSeq = ack.messageSequence

        val finalTicket = ByteBuffer.allocate(authTicket.size + 4 + appOwnershipTicket.size)
            .order(ByteOrder.LITTLE_ENDIAN)
            .put(authTicket)
            .putInt(appOwnershipTicket.size)
            .put(appOwnershipTicket)
            .array()
        if (finalTicket.size > MAX_TICKET_BYTES) {
            throw SteamTicketException("Minted Steam WebAPI ticket size invalid", stage = "lease")
        }
        steamSessionTicket = finalTicket.joinToString("") { "%02X".format(it) }
        return steamSessionTicket
    }

    fun ensureLease(expectedSteamIdHash: String? = null): String = synchronized(lock) {
        val cm = ensureLiveCm(expectedSteamIdHash)
        if (steamSessionTicket.isNotEmpty() && cm.alive && cm.loggedOn) return steamSessionTicket
        return try {
            mintFromLiveCm(cm)
        } catch (exc: SteamTicketException) {
            if (!exc.transport && exc.safeReason != "timeout") throw exc
            liveSession?.close()
            liveSession = null
            mintFromLiveCm(ensureLiveCm(expectedSteamIdHash))
        }
    }

    fun refresh(): String = synchronized(lock) {
        val cm = ensureLiveCm(boundSteamIdHash)
        mintFromLiveCm(cm)
    }

    override fun close() = synchronized(lock) {
        closeAuthCm()
        liveSession?.close()
        liveSession = null
        steamSessionTicket = ""
    }

    companion object {
        const val APP_ID = 3224770
        val SERVER_SECRET: ByteArray = "str:unityauthenticationservice\u0000".toByteArray(Charsets.US_ASCII)
        const val TICKET_TYPE_WEBAPI = 5
        const val MAX_REFRESH_TOKEN_BYTES = 16 * 1024
        const val MAX_TICKET_BYTES = 2560
        const val NO_JOB_ID = -1L
        const val ERESULT_OK = 1
        const val ERESULT_EXPIRED = 27
        const val ERESULT_TRY_ANOTHER_CM = 48

        const val CM_DISCOVERY_URL =
            "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/?cmtype=websockets&cellid=0"
        const val METHOD_BEGIN_QR = "Authentication.BeginAuthSessionViaQR#1"
        const val METHOD_GET_RSA_KEY = "Authentication.GetPasswordRSAPublicKey#1"
        const val METHOD_BEGIN_CREDENTIALS = "Authentication.BeginAuthSessionViaCredentials#1"
        const val METHOD_UPDATE_GUARD_CODE = "Authentication.UpdateAuthSessionWithSteamGuardCode#1"
        const val METHOD_POLL_STATUS = "Authentication.PollAuthSessionStatus#1"

        const val GUARD_NONE = 1
        const val GUARD_EMAIL_CODE = 2
        const val GUARD_DEVICE_CODE = 3
        const val GUARD_DEVICE_CONFIRMATION = 4
        const val GUARD_EMAIL_CONFIRMATION = 5

        internal val rng = SecureRandom()

        fun guardSlug(type: Int): String? = when (type) {
            GUARD_EMAIL_CODE -> "email_code"
            GUARD_DEVICE_CODE -> "device_code"
            GUARD_DEVICE_CONFIRMATION -> "device_confirm"
            GUARD_EMAIL_CONFIRMATION -> "email_confirm"
            else -> null
        }

        fun friendlyEresultMessage(methodName: String, er: Int): String = when (er) {
            5 -> "Incorrect Steam username or password"
            65 -> "Incorrect email Steam Guard code"
            84 -> "Too many Steam login attempts — wait before retrying"
            88, 89 -> "Incorrect Steam Guard authenticator code"
            else -> "Steam rejected $methodName (eresult=$er)"
        }

        fun encryptPasswordRsa(password: String, modHex: String, expHex: String): String {
            val modulus = BigInteger(modHex.trim(), 16)
            val exponent = BigInteger(expHex.trim(), 16)
            val spec = RSAPublicKeySpec(modulus, exponent)
            val pubKey = KeyFactory.getInstance("RSA").generatePublic(spec)
            val cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
            cipher.init(Cipher.ENCRYPT_MODE, pubKey)
            return Base64.getEncoder().encodeToString(cipher.doFinal(password.toByteArray(Charsets.UTF_8)))
        }

        fun decodeSteamRefreshJwt(token: String): String {
            val cleaned = token.trim()
            if (cleaned.isEmpty() || '\n' in cleaned || '\r' in cleaned) {
                throw SteamTicketException("Refresh token whitespace invalid", stage = "token", safeReason = "invalid_token")
            }
            val parts = cleaned.split('.')
            if (parts.size != 3 || parts.any { it.isEmpty() }) {
                throw SteamTicketException("Refresh token is not a 3-part JWT", stage = "token", safeReason = "invalid_token")
            }
            val claims = try {
                val raw = Base64.getUrlDecoder().decode(parts[1])
                JsonCodec.decodeMap(raw.toString(Charsets.UTF_8))
            } catch (exc: Exception) {
                throw SteamTicketException("Refresh token JWT payload malformed", stage = "token", safeReason = "invalid_token", cause = exc)
            }
            if (claims["iss"] != "steam") {
                throw SteamTicketException("Refresh token issuer must be steam", stage = "token", safeReason = "invalid_token")
            }
            val audList = when (val a = claims["aud"]) {
                is String -> listOf(a)
                is List<*> -> a.mapNotNull { it?.toString() }
                else -> emptyList()
            }
            if ("client" !in audList || "derive" !in audList) {
                throw SteamTicketException("token audience missing client/derive", stage = "token", safeReason = "invalid_token")
            }
            val sub = (claims["sub"] ?: "").toString().trim()
            if (sub.length != 17 || !sub.all { it.isDigit() } || (sub.toLongOrNull() ?: 0L) <= 0L) {
                throw SteamTicketException("token subject is not a SteamID64", stage = "token", safeReason = "invalid_token")
            }
            return sub
        }

        fun buildWebapiAuthTicket(gcToken: ByteArray, sequence: Int, elapsedMs: Int, nonce: ByteArray): ByteArray {
            require(nonce.size == 8) { "Auth ticket nonce must be 8 bytes" }
            return ByteBuffer.allocate(4 + gcToken.size + 28)
                .order(ByteOrder.LITTLE_ENDIAN)
                .putInt(gcToken.size)
                .put(gcToken)
                .putInt(24)
                .putInt(1)
                .putInt(TICKET_TYPE_WEBAPI)
                .put(nonce)
                .putInt(elapsedMs)
                .putInt(sequence)
                .array()
        }
    }
}
