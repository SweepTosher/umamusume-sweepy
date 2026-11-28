package top.mayano.sweepy.core

import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.UUID

class HeadlessAuthException(
    message: String,
    val code: Int? = null,
    val endpoint: String? = null,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

data class DeviceStateRecord(
    val schema: Int = DeviceIdentity.STATE_SCHEMA,
    val udid: String,
    val deviceId: String,
    val phase: String = "established",
    val viewerId: String,
    val authKeyHex: String,
    val steamIdHash: String,
    val provenance: String = "server-issued",
    val resourceVersion: String = DeviceIdentity.DEFAULT_RES_VER,
    val resourceVersionKnown: Boolean = true,
) {
    fun toMap(): LinkedHashMap<String, Any?> = linkedMapOf(
        "schema" to schema,
        "udid" to udid,
        "device_id" to deviceId,
        "phase" to phase,
        "viewer_id" to viewerId,
        "auth_key" to authKeyHex,
        "steam_id_hash" to steamIdHash,
        "provenance" to provenance,
        "resource_version" to resourceVersion,
    )
}

object DeviceIdentity {
    const val STATE_SCHEMA = 5
    const val PORTABLE_WINDOWS_OS = "Windows 10  (10.0.19045) 64bit"
    const val DEFAULT_LOCALE = "JPN"
    const val DEFAULT_RES_VER = "10007550"

    private val DEVICE_ID_RE = Regex("^[0-9a-f]{40}$")
    private val AUTH_KEY_RE = Regex("^[0-9a-f]{96}$")
    private val STEAM_HASH_RE = Regex("^[0-9a-f]{64}$")
    private val RES_VER_RE = Regex("^[0-9]{1,32}$")

    fun isValidDeviceId(value: String): Boolean = DEVICE_ID_RE.matches(value)

    fun computeSteamIdHash(steamId: String): String {
        val text = steamId.trim()
        if (text.length != 17 || !text.all { it.isDigit() } || (text.toLongOrNull() ?: 0L) <= 0L) {
            throw HeadlessAuthException("not a 17-digit SteamID64")
        }
        return MessageDigest.getInstance("SHA-256")
            .digest(text.toByteArray(Charsets.US_ASCII))
            .joinToString("") { "%02x".format(it) }
    }

    fun localIp(): String = try {
        DatagramSocket().use { sock ->
            sock.connect(InetAddress.getByName("198.51.100.1"), 80)
            sock.localAddress?.hostAddress?.takeIf { it.isNotBlank() } ?: "127.0.0.1"
        }
    } catch (_: Exception) {
        "127.0.0.1"
    }

    fun runtimeDeviceFields(
        udid: String,
        deviceId: String?,
        store: RuntimeStore? = null,
    ): LinkedHashMap<String, Any?> {
        runCatching { UUID.fromString(udid.trim()) }
            .getOrElse { throw HeadlessAuthException("udid must be a valid UUID string", cause = it) }

        val resolvedId = if (deviceId.isNullOrBlank()) {
            store?.loadOrCreatePersistentDeviceId() ?: PrivateFiles.randomHex(20)
        } else {
            deviceId.trim().lowercase().also {
                if (!DEVICE_ID_RE.matches(it)) throw HeadlessAuthException("bad device_id")
            }
        }

        return linkedMapOf(
            "device" to 4,
            "device_id" to resolvedId,
            "device_name" to "Windows PC",
            "graphics_device_name" to "Direct3D 11",
            "ip_address" to localIp(),
            "platform_os_version" to PORTABLE_WINDOWS_OS,
            "carrier" to "",
            "keychain" to 0,
            "locale" to DEFAULT_LOCALE,
            "button_info" to "",
            "dmm_viewer_id" to null,
            "dmm_onetime_token" to null,
        )
    }

    fun recordFromMap(raw: Map<String, Any?>): DeviceStateRecord {
        val normUdid = try {
            UUID.fromString((raw["udid"] ?: "").toString().trim()).toString()
        } catch (exc: Exception) {
            throw HeadlessAuthException("Invalid udid for headless_device.json", cause = exc)
        }
        val normDeviceId = (raw["device_id"] ?: "").toString().trim().lowercase()
        if (!DEVICE_ID_RE.matches(normDeviceId)) {
            throw HeadlessAuthException("Invalid device_id for headless_device.json")
        }
        val vid = JsonCodec.asLongOrNull(raw["viewer_id"])
            ?: throw HeadlessAuthException("Invalid viewer_id for headless_device.json")
        if (vid <= 0L) throw HeadlessAuthException("viewer_id must be positive")

        val authRaw = raw["auth_key"]
        val normAuth = when (authRaw) {
            is ByteArray -> authRaw.joinToString("") { "%02x".format(it) }
            else -> (authRaw ?: "").toString().trim().lowercase()
        }
        if (!AUTH_KEY_RE.matches(normAuth)) {
            throw HeadlessAuthException("auth_key must be 48 bytes (96 hex chars)")
        }
        val normHash = (raw["steam_id_hash"] ?: "").toString().trim().lowercase()
        if (!STEAM_HASH_RE.matches(normHash)) {
            throw HeadlessAuthException("steam_id_hash must be 64 lowercase hex chars")
        }
        val rawRv = (raw["resource_version"] ?: DEFAULT_RES_VER).toString().trim()
        val normRv = if (RES_VER_RE.matches(rawRv) && (rawRv.toLongOrNull() ?: 0L) > 0L) rawRv else DEFAULT_RES_VER
        return DeviceStateRecord(
            udid = normUdid,
            deviceId = normDeviceId,
            viewerId = vid.toString(),
            authKeyHex = normAuth,
            steamIdHash = normHash,
            resourceVersion = normRv,
            resourceVersionKnown = rawRv == normRv,
        )
    }

    fun readDeviceState(path: Path, expectedSteamIdHash: String? = null): DeviceStateRecord? {
        if (!Files.exists(path)) return null
        if (Files.isSymbolicLink(path) || !Files.isRegularFile(path)) {
            throw HeadlessAuthException("headless_device.json is not a regular file")
        }
        val parsed = try {
            JsonCodec.decodeMap(Files.readString(path, Charsets.UTF_8))
        } catch (exc: Exception) {
            throw HeadlessAuthException("headless_device.json contains malformed JSON", cause = exc)
        }
        if (JsonCodec.asInt(parsed["schema"], -1) != STATE_SCHEMA) {
            throw HeadlessAuthException("Unsupported headless_device.json schema: ${parsed["schema"]}")
        }
        if (parsed["phase"] != "established") throw HeadlessAuthException("phase is not established")
        if (parsed["provenance"] != "server-issued") throw HeadlessAuthException("provenance is not server-issued")

        val record = recordFromMap(parsed)
        if (expectedSteamIdHash != null && record.steamIdHash != expectedSteamIdHash.trim().lowercase()) {
            throw HeadlessAuthException("device file belongs to another account")
        }
        return record
    }

    fun writeDeviceState(path: Path, record: DeviceStateRecord): Path {
        PrivateFiles.atomicWriteUtf8(path, JsonCodec.encode(record.toMap()) + "\n")
        return path
    }
}
