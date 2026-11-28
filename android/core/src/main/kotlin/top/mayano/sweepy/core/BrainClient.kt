package top.mayano.sweepy.core

import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.util.Collections
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

open class BrainApiException(
    message: String,
    val statusCode: Int? = null,
    val code: String? = null,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

class ContractMismatchException(message: String) : BrainApiException(message)

class BrainClient(
    apiUrl: String,
    apiKey: String,
    private val http: OkHttpClient,
    timeoutSec: Long = 15L,
    var onKeyRefresh: ((String) -> Unit)? = null,
) : Closeable {
    val apiUrl: String = try {
        validateBrainUrl(apiUrl)
    } catch (exc: IllegalArgumentException) {
        throw BrainApiException("bad api_url $apiUrl: ${exc.message}", cause = exc)
    }

    @Volatile
    var apiKey: String = apiKey.trim()
        private set

    private val callClient: OkHttpClient = http.newBuilder()
        .callTimeout(timeoutSec, TimeUnit.SECONDS)
        .readTimeout(timeoutSec, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

    private val activeCalls = Collections.synchronizedSet(HashSet<Call>())

    private fun baseHeadersBuilder(): Request.Builder = Request.Builder()
        .header("Accept", "application/json")
        .header("X-Sweepy-Client", "2.0")
        .apply {
            val k = apiKey
            if (k.isNotEmpty()) {
                header("Authorization", "Bearer $k")
            }
        }

    fun meta(): Map<String, Any?> {
        val url = "$apiUrl/v1/meta"
        val req = baseHeadersBuilder().url(url).get().build()
        val (status, bytes) = execute(req, "meta")
        if (status != 200) {
            throw BrainApiException("meta: HTTP $status: ${preview(bytes)}", statusCode = status, code = errorCodeFromBody(bytes))
        }
        val parsed = decodeResponseBytes(bytes)
        if (parsed["ok"] != true) throw BrainApiException("meta missing ok")
        return parsed
    }

    fun health(): Map<String, Any?> {
        val url = "$apiUrl/v1/health"
        val req = baseHeadersBuilder().url(url).get().build()
        val (status, bytes) = execute(req, "health")
        if (status != 200) {
            throw BrainApiException("health: HTTP $status: ${preview(bytes)}", statusCode = status)
        }
        val parsed = decodeResponseBytes(bytes)
        val model = (parsed["model"] as? String)?.trim().orEmpty()
        if (parsed["ok"] != true || model.isEmpty()) {
            throw BrainApiException("health payload missing model")
        }
        return parsed
    }

    fun requestNewKey(): String {
        val url = "$apiUrl/v1/keys"
        val req = Request.Builder()
            .url(url)
            .header("Accept", "application/json")
            .header("X-Sweepy-Client", "2.0")
            .post(ByteArray(0).toRequestBody(null))
            .build()
        val (status, bytes) = execute(req, "key")
        if (status != 200) {
            throw BrainApiException("key: HTTP $status: ${preview(bytes, 200)}", statusCode = status, code = errorCodeFromBody(bytes))
        }
        val payload = decodeResponseBytes(bytes)
        val secret = (payload["api_key"] ?: "").toString().trim()
        if (secret.isEmpty()) throw BrainApiException("key response missing api_key")
        apiKey = secret
        onKeyRefresh?.invoke(secret)
        return secret
    }

    fun decide(
        viewerIdHash: String,
        state: Map<String, Any?>,
        delta: Map<String, Any?>,
        options: Map<String, Any?>,
    ): Map<String, Any?> {
        if (apiKey.isEmpty()) throw BrainApiException("no api key")
        if (viewerIdHash.isBlank()) throw BrainApiException("viewer_id_hash is empty")

        val bodyObj = linkedMapOf(
            "viewer_id_hash" to viewerIdHash,
            "state" to state,
            "delta" to delta,
            "options" to options,
        )
        val compressed = gzipCompress(JsonCodec.encode(bodyObj).toByteArray(Charsets.UTF_8))
        val url = "$apiUrl/v1/gl/decide"

        var respStatus = 0
        var respBytes = ByteArray(0)
        for (attempt in 0..1) {
            val req = baseHeadersBuilder()
                .url(url)
                .header("Content-Encoding", "gzip")
                .post(compressed.toRequestBody(JSON_MEDIA))
                .build()
            val pair = execute(req, "decide")
            respStatus = pair.first
            respBytes = pair.second
            if (attempt == 0 && respStatus == 403 && errorCodeFromBody(respBytes) == "key_exhausted") {
                requestNewKey()
                continue
            }
            break
        }

        if (respStatus != 200) {
            val detail = errorDetailFromBody(respBytes)
            throw BrainApiException(
                detail.ifEmpty { "decide: HTTP $respStatus" },
                statusCode = respStatus,
                code = errorCodeFromBody(respBytes),
            )
        }

        val parsed = decodeResponseBytes(respBytes)
        val op = parsed["op"]?.toString()
        val params = JsonCodec.asMap(parsed["params"])
        if (op !in VALID_BRAIN_OPS || params == null) {
            throw BrainApiException("bad decision: op=$op")
        }
        return parsed
    }

    fun closeCareer(viewerIdHash: String): Map<String, Any?> {
        if (apiKey.isEmpty()) throw BrainApiException("no api key")
        if (viewerIdHash.isBlank()) throw BrainApiException("viewer_id_hash is empty")
        val compressed = gzipCompress(
            JsonCodec.encode(mapOf("viewer_id_hash" to viewerIdHash)).toByteArray(Charsets.UTF_8)
        )
        val url = "$apiUrl/v1/gl/close"
        val req = baseHeadersBuilder()
            .url(url)
            .header("Content-Encoding", "gzip")
            .post(compressed.toRequestBody(JSON_MEDIA))
            .build()
        val (status, bytes) = execute(req, "close")
        if (status != 200) {
            throw BrainApiException("close: HTTP $status: ${preview(bytes, 300)}", statusCode = status, code = errorCodeFromBody(bytes))
        }
        val parsed = decodeResponseBytes(bytes)
        if (parsed["ok"] != true) throw BrainApiException("close missing ok")
        return parsed
    }

    private fun execute(req: Request, label: String): Pair<Int, ByteArray> {
        val call = callClient.newCall(req)
        activeCalls.add(call)
        return try {
            call.execute().use { resp ->
                val raw = resp.body.bytes()
                resp.code to raw
            }
        } catch (exc: Exception) {
            throw BrainApiException("$label request failed (${req.url}): ${exc.message}", cause = exc)
        } finally {
            activeCalls.remove(call)
        }
    }

    override fun close() {
        val snapshot = synchronized(activeCalls) { activeCalls.toList() }
        for (c in snapshot) c.cancel()
    }

    companion object {
        const val MAX_RESPONSE_BYTES = 4 * 1024 * 1024
        const val CLIENT_CONTRACT_VERSION = "1"
        val VALID_BRAIN_OPS = setOf("rpc_step", "race_macro", "race_resume_macro", "terminal_skills", "terminal_finish")
        val TERMINAL_OPS = setOf("terminal_skills", "terminal_finish")
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        fun verifyContract(meta: Map<String, Any?>): List<String> {
            val version = (meta["contract_version"] ?: "").toString()
            if (version != CLIENT_CONTRACT_VERSION) {
                throw ContractMismatchException("contract ${version.ifEmpty { "unknown" }} != $CLIENT_CONTRACT_VERSION")
            }
            val emitted = JsonCodec.asList(meta["emitted_ops"])
            if (emitted == null || emitted.isEmpty()) {
                throw ContractMismatchException("meta has no emitted_ops")
            }
            val emittedSet = emitted.map { it.toString() }.toSet()
            val unsupported = emittedSet.filter { it !in VALID_BRAIN_OPS }.sorted()
            if (unsupported.isNotEmpty()) {
                throw ContractMismatchException("unsupported opcodes: $unsupported")
            }
            val warnings = mutableListOf<String>()
            if (TERMINAL_OPS.any { it in emittedSet }) {
                warnings.add("terminal ops declared but unimplemented")
            }
            val brainKeys = JsonCodec.asList(meta["state_keys"])?.map { it.toString() }?.toSet()
            if (brainKeys != null) {
                val ours = StateStripper.ALLOWED_TOP_KEYS
                val missing = (brainKeys - ours).sorted()
                val extra = (ours - brainKeys).sorted()
                if (missing.isNotEmpty()) warnings.add("brain expects stripped keys: $missing")
                if (extra.isNotEmpty()) warnings.add("brain ignores sent keys: $extra")
            }
            return warnings
        }

        private fun gzipCompress(raw: ByteArray): ByteArray {
            val out = ByteArrayOutputStream(raw.size / 2 + 32)
            GZIPOutputStream(out).use { it.write(raw) }
            return out.toByteArray()
        }

        private fun gunzipLimited(raw: ByteArray): ByteArray {
            return try {
                GZIPInputStream(ByteArrayInputStream(raw)).use { gz ->
                    val out = ByteArrayOutputStream()
                    val buf = ByteArray(8192)
                    var total = 0
                    while (true) {
                        val n = gz.read(buf)
                        if (n < 0) break
                        total += n
                        if (total > MAX_RESPONSE_BYTES) {
                            throw BrainApiException("response too large after gunzip")
                        }
                        out.write(buf, 0, n)
                    }
                    out.toByteArray()
                }
            } catch (exc: BrainApiException) {
                throw exc
            } catch (exc: Exception) {
                throw BrainApiException("bad gzip: ${exc.message}", cause = exc)
            }
        }

        private fun unwrapPossiblyGzipped(raw: ByteArray): ByteArray {
            val data = if (raw.size >= 2 && raw[0] == 0x1F.toByte() && raw[1] == 0x8B.toByte()) {
                gunzipLimited(raw)
            } else {
                raw
            }
            if (data.size > MAX_RESPONSE_BYTES) {
                throw BrainApiException("response too large")
            }
            return data
        }

        private fun decodeResponseBytes(raw: ByteArray): Map<String, Any?> {
            if (raw.isEmpty()) throw BrainApiException("empty body")
            val data = unwrapPossiblyGzipped(raw)
            return try {
                JsonCodec.decodeMap(data.toString(Charsets.UTF_8))
            } catch (exc: Exception) {
                throw BrainApiException("bad json: ${exc.message}", cause = exc)
            }
        }

        private fun errorCodeFromBody(raw: ByteArray): String? {
            if (raw.isEmpty()) return null
            val parsed = runCatching {
                JsonCodec.decodeMap(unwrapPossiblyGzipped(raw).toString(Charsets.UTF_8))
            }.getOrNull() ?: return null
            (parsed["code"] as? String)?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
            when (val err = parsed["error"]) {
                is String -> err.trim().takeIf { it.isNotEmpty() }?.let { return it }
                is Map<*, *> -> (err["code"] as? String)?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
            }
            return null
        }

        private fun errorDetailFromBody(raw: ByteArray): String {
            if (raw.isEmpty()) return ""
            val parsed = runCatching {
                JsonCodec.decodeMap(unwrapPossiblyGzipped(raw).toString(Charsets.UTF_8))
            }.getOrNull() ?: return ""
            val d = parsed["detail"]
            val msg = when (d) {
                is Map<*, *> -> (d["message"] ?: d["detail"])?.toString()
                is String -> d
                else -> null
            } ?: return ""
            return msg.trim().split(Regex("\\s+")).joinToString(" ").take(200)
        }

        private fun preview(raw: ByteArray, max: Int = 240): String =
            runCatching { unwrapPossiblyGzipped(raw).toString(Charsets.UTF_8) }
                .getOrElse { "" }
                .trim()
                .take(max)
    }
}
