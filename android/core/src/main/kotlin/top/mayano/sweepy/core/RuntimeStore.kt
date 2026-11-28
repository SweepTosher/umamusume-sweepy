package top.mayano.sweepy.core

import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.SecureRandom
import kotlin.math.max
import kotlin.math.min
import kotlin.math.round

object AppConstants {
    const val CM_ENABLED = false
}

val CM_ROLE_ALIASES: Map<String, Int> = mapOf(
    "solo" to 0, "ace1" to 0, "raw" to 0, "ace1_raw" to 0,
    "ace" to 1, "ace2" to 1,
    "support" to 2, "debuffer" to 2, "deb" to 2,
    "blocker" to 3, "blk" to 3,
)

val CM_STYLE_ALIASES: Map<String, Int> = mapOf(
    "auto" to 0,
    "front" to 1, "nige" to 1,
    "pace" to 2, "senko" to 2,
    "late" to 3, "sashi" to 3,
    "end" to 4, "oikomi" to 4,
    "runaway" to 5, "oonige" to 5,
)

private val LOOPBACK_HOSTS = setOf("127.0.0.1", "localhost", "::1")

data class TurnDelayConfig(
    val min: Double = 1.6,
    val max: Double = 3.7,
    val restoreMin: Double = 1.6,
    val restoreMax: Double = 3.7,
    val disabled: Boolean = false,
) {
    fun toMap(): LinkedHashMap<String, Any?> = linkedMapOf(
        "min" to min,
        "max" to max,
        "restore_min" to restoreMin,
        "restore_max" to restoreMax,
        "disabled" to disabled,
    )
}

fun defaultCmConfigMap(): LinkedHashMap<String, Any?> = linkedMapOf(
    "cm_mode" to false,
    "cm_preset" to "sagittarius",
    "cm_course" to "sagittarius",
    "track" to "Nakayama",
    "distance" to 2500,
    "ground" to 1,
    "ground_condition" to 1,
    "weather" to 1,
    "season" to 4,
    "course_id" to 10506,
    "inout" to 1,
    "cm_role" to 0,
    "cm_target" to "carry",
    "cm_style" to 0,
    "mate_ids" to mutableListOf<Any?>(null, null),
    "mate_roles" to mutableListOf("auto", "auto"),
    "mate_snapshots" to mutableListOf<Any?>(null, null),
)

fun parseCmIntOrAlias(raw: Any?, aliases: Map<String, Int>, lo: Int, hi: Int, default: Int): Int {
    if (raw == null || raw is Boolean) return default
    val iv = when (raw) {
        is String -> {
            val key = raw.trim().lowercase()
            if (key.isEmpty()) return default
            aliases[key] ?: key.toIntOrNull() ?: return default
        }
        else -> JsonCodec.asLongOrNull(raw)?.toInt() ?: return default
    }
    return max(lo, min(hi, iv))
}

fun normalizeCmRole(rawRole: Any?, target: Any? = null): Int {
    val role = parseCmIntOrAlias(rawRole, CM_ROLE_ALIASES, 0, 3, 0)
    if (role == 1 && (target?.toString()?.trim()?.lowercase() ?: "carry") == "debuffer") {
        return 2
    }
    return role
}

fun normalizeCmStyle(rawStyle: Any?): Int = parseCmIntOrAlias(rawStyle, CM_STYLE_ALIASES, 0, 5, 0)

fun normalizeCmConfig(raw: Any?): LinkedHashMap<String, Any?> {
    val src = JsonCodec.asMap(raw) ?: emptyMap()
    val defaults = defaultCmConfigMap()
    val cmMode = JsonCodec.asBool(src["cm_mode"], false)
    val rawCourse = src["cm_course"]
    val courseDict = JsonCodec.asMap(rawCourse) ?: emptyMap()
    val cmCourse: Any = when (rawCourse) {
        is String -> rawCourse.trim().ifEmpty { "sagittarius" }
        is Map<*, *> -> JsonCodec.asMutableMap(rawCourse) ?: "sagittarius"
        else -> "sagittarius"
    }
    val rawPreset = src["cm_preset"] ?: (cmCourse as? String) ?: courseDict["slug"] ?: "custom"
    val cmPreset = rawPreset.toString().trim().ifEmpty { "custom" }

    val track = (src["track"] ?: courseDict["track"] ?: defaults["track"]).toString().trim()
        .ifEmpty { defaults["track"] as String }
    val distance = parseCmIntOrAlias(src["distance"] ?: courseDict["distance"], emptyMap(), 1000, 3600, 2500)
    val ground = parseCmIntOrAlias(
        src["ground"] ?: src["surface"] ?: courseDict["ground"] ?: courseDict["surface"],
        mapOf("turf" to 1, "grass" to 1, "shiba" to 1, "dirt" to 2, "sand" to 2),
        1, 2, 1,
    )
    val groundCondition = parseCmIntOrAlias(
        src["ground_condition"] ?: courseDict["ground_condition"],
        mapOf("firm" to 1, "good" to 2, "soft" to 3, "yielding" to 3, "heavy" to 4, "bad" to 4),
        1, 4, 1,
    )
    val weather = parseCmIntOrAlias(
        src["weather"] ?: courseDict["weather"],
        mapOf("sunny" to 1, "clear" to 1, "cloudy" to 2, "rainy" to 3, "rain" to 3, "snowy" to 4, "snow" to 4),
        1, 4, 1,
    )
    val season = parseCmIntOrAlias(
        src["season"] ?: courseDict["season"],
        mapOf("spring" to 1, "summer" to 2, "autumn" to 3, "fall" to 3, "winter" to 4),
        1, 4, 4,
    )
    val rawCid = src["course_id"] ?: courseDict["course_id"]
    val courseId = JsonCodec.asLongOrNull(rawCid)?.toInt()?.takeIf { it > 0 }
    val inout = parseCmIntOrAlias(
        src["inout"] ?: courseDict["inout"],
        mapOf("inner" to 1, "in" to 1, "outer" to 2, "out" to 2),
        1, 2, 1,
    )
    val cmRole = parseCmIntOrAlias(src["cm_role"] ?: 0, CM_ROLE_ALIASES, 0, 3, 0)
    val rawTarget = (src["cm_target"] ?: "carry").toString().trim().lowercase()
    val cmTarget = if (rawTarget in setOf("carry", "debuffer")) rawTarget else "carry"
    val cmStyle = normalizeCmStyle(src["cm_style"] ?: 0)

    val mateIds = mutableListOf<Any?>(null, null)
    val rawIds = JsonCodec.asList(src["mate_ids"])
    if (rawIds != null) {
        for (i in 0 until min(2, rawIds.size)) {
            mateIds[i] = JsonCodec.asLongOrNull(rawIds[i])?.toInt()
        }
    }
    val mateRoles = mutableListOf("auto", "auto")
    val rawRoles = JsonCodec.asList(src["mate_roles"])
    if (rawRoles != null) {
        for (i in 0 until min(2, rawRoles.size)) {
            val rv = (rawRoles[i] ?: "auto").toString().trim().lowercase()
            mateRoles[i] = if (rv in setOf("auto", "ace", "debuffer", "blocker")) rv else "auto"
        }
    }
    val mateSnapshots = mutableListOf<Any?>(null, null)
    val rawSnaps = JsonCodec.asList(src["mate_snapshots"])
    if (rawSnaps != null) {
        for (i in 0 until min(2, rawSnaps.size)) {
            val m = JsonCodec.asMutableMap(rawSnaps[i])
            if (m != null) mateSnapshots[i] = m
        }
    }

    return linkedMapOf(
        "cm_mode" to cmMode,
        "cm_preset" to cmPreset,
        "cm_course" to cmCourse,
        "track" to track,
        "distance" to distance,
        "ground" to ground,
        "ground_condition" to groundCondition,
        "weather" to weather,
        "season" to season,
        "course_id" to courseId,
        "inout" to inout,
        "cm_role" to cmRole,
        "cm_target" to cmTarget,
        "cm_style" to cmStyle,
        "mate_ids" to mateIds,
        "mate_roles" to mateRoles,
        "mate_snapshots" to mateSnapshots,
    )
}

fun normalizeTurnDelay(raw: Any?): TurnDelayConfig {
    val src = JsonCodec.asMap(raw) ?: emptyMap()
    val disabled = JsonCodec.asBool(src["disabled"], false)
    var restoreMin = max(0.0, JsonCodec.asDouble(src["restore_min"] ?: src["min"], 1.6))
    var restoreMax = max(restoreMin, JsonCodec.asDouble(src["restore_max"] ?: src["max"], 3.7))
    val curMin: Double
    val curMax: Double
    if (disabled) {
        curMin = 0.0
        curMax = 0.0
    } else {
        curMin = max(0.0, JsonCodec.asDouble(src["min"], restoreMin))
        curMax = max(curMin, JsonCodec.asDouble(src["max"], restoreMax))
        restoreMin = curMin
        restoreMax = curMax
    }
    fun r3(v: Double) = round(v * 1000.0) / 1000.0
    return TurnDelayConfig(
        min = r3(curMin),
        max = r3(curMax),
        restoreMin = r3(restoreMin),
        restoreMax = r3(restoreMax),
        disabled = disabled,
    )
}

fun validateBrainUrl(apiUrl: String?): String {
    val cleaned = (apiUrl ?: "").trim().trimEnd('/')
    if (cleaned.isEmpty()) throw IllegalArgumentException("api_url is empty")
    if (cleaned.any { it.isWhitespace() || it.code < 0x20 || it.code == 0x7F }) {
        throw IllegalArgumentException("api_url has whitespace or control characters")
    }
    val uri = try {
        URI(cleaned)
    } catch (exc: Exception) {
        throw IllegalArgumentException("invalid api_url: ${exc.message}")
    }
    val scheme = (uri.scheme ?: "").lowercase()
    if (scheme !in setOf("https", "http")) {
        throw IllegalArgumentException("api_url must start with https:// or http://")
    }
    val host = uri.host?.lowercase()?.trim('[', ']') ?: throw IllegalArgumentException("api_url must include a host")
    if (uri.port != -1 && uri.port !in 1..65535) {
        throw IllegalArgumentException("api_url port is not 1-65535")
    }
    if (!uri.userInfo.isNullOrEmpty()) {
        throw IllegalArgumentException("api_url has embedded credentials")
    }
    if (!uri.rawQuery.isNullOrEmpty() || !uri.rawFragment.isNullOrEmpty()) {
        throw IllegalArgumentException("api_url has a query or fragment")
    }
    if (scheme == "http" && host !in LOOPBACK_HOSTS) {
        throw IllegalArgumentException("http api_url is only allowed for loopback brains; use https otherwise")
    }
    return cleaned
}

object PrivateFiles {
    private val rng = SecureRandom()

    fun ensurePrivateDir(dir: Path): Path {
        Files.createDirectories(dir)
        runCatching {
            Files.setPosixFilePermissions(dir, PosixFilePermissions.fromString("rwx------"))
        }
        return dir.toAbsolutePath().normalize()
    }

    fun atomicWriteBytes(path: Path, bytes: ByteArray) {
        val parent = path.toAbsolutePath().normalize().parent ?: error("Missing parent path")
        ensurePrivateDir(parent)
        val tmp = Files.createTempFile(parent, ".tmp_", ".part")
        try {
            runCatching {
                Files.setPosixFilePermissions(tmp, PosixFilePermissions.fromString("rw-------"))
            }
            Files.write(tmp, bytes)
            try {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            } catch (_: Exception) {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING)
            }
            runCatching {
                Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rw-------"))
            }
        } catch (t: Throwable) {
            Files.deleteIfExists(tmp)
            throw t
        }
    }

    fun atomicWriteUtf8(path: Path, text: String) {
        atomicWriteBytes(path, text.toByteArray(Charsets.UTF_8))
    }

    fun randomHex(byteCount: Int): String {
        val buf = ByteArray(byteCount)
        rng.nextBytes(buf)
        return buf.joinToString("") { "%02x".format(it) }
    }
}

data class RuntimeSettings(
    val apiUrl: String,
    val apiKey: String,
    val turnDelay: TurnDelayConfig,
    val burnClocks: Boolean,
    val cmConfig: LinkedHashMap<String, Any?>,
)

class RuntimeStore(runtimeDir: Path) {
    val runtimeDir: Path = PrivateFiles.ensurePrivateDir(runtimeDir)
    val settingsFile: Path = this.runtimeDir.resolve("settings.json")
    val refreshFile: Path = this.runtimeDir.resolve("steam_refresh.token")
    val deviceFile: Path = this.runtimeDir.resolve("headless_device.json")
    val saltFile: Path = this.runtimeDir.resolve("account_salt")
    val timingSeedFile: Path = this.runtimeDir.resolve(".timing_dna")
    val apiKeyFile: Path = this.runtimeDir.resolve("brain_api.key")
    val generatedDeviceIdFile: Path = this.runtimeDir.resolve(".device_id")

    private val lock = Any()
    private var memoryApiKey: String = ""

    init {
        synchronized(lock) {
            ensureDefaults()
            adoptLegacyOrDiskApiKey()
        }
    }

    private fun defaultApiUrl(): String {
        val envUrl = (System.getenv("SWEEPY_API_URL") ?: "https://mayano.top/sweepy").trim().trimEnd('/')
        return envUrl.ifEmpty { "https://mayano.top/sweepy" }
    }

    private fun defaultSettings(): RuntimeSettings = RuntimeSettings(
        apiUrl = defaultApiUrl(),
        apiKey = memoryApiKey,
        turnDelay = TurnDelayConfig(),
        burnClocks = false,
        cmConfig = defaultCmConfigMap(),
    )

    private fun diskPayload(settings: RuntimeSettings): LinkedHashMap<String, Any?> = linkedMapOf(
        "api_url" to settings.apiUrl,
        "turn_delay" to settings.turnDelay.toMap(),
        "burn_clocks" to settings.burnClocks,
        "cm_config" to normalizeCmConfig(settings.cmConfig),
    )

    private fun ensureDefaults() {
        if (!Files.isRegularFile(settingsFile)) {
            PrivateFiles.atomicWriteUtf8(settingsFile, JsonCodec.encodePretty(diskPayload(defaultSettings())))
        }
    }

    private fun adoptLegacyOrDiskApiKey() {
        val envKey = (System.getenv("SWEEPY_API_KEY") ?: "").trim()
        if (envKey.isNotEmpty()) {
            memoryApiKey = envKey
            return
        }
        if (Files.isRegularFile(apiKeyFile)) {
            runCatching {
                val disk = Files.readString(apiKeyFile, Charsets.UTF_8).trim()
                if (disk.isNotEmpty()) memoryApiKey = disk
            }
        }
        runCatching {
            val raw = JsonCodec.decodeMap(Files.readString(settingsFile, Charsets.UTF_8))
            if ("api_key" in raw) {
                val legacy = (raw.remove("api_key") ?: "").toString().trim()
                PrivateFiles.atomicWriteUtf8(settingsFile, JsonCodec.encodePretty(raw))
                if (legacy.isNotEmpty() && memoryApiKey.isEmpty()) {
                    memoryApiKey = legacy
                    PrivateFiles.atomicWriteUtf8(apiKeyFile, "$legacy\n")
                }
            }
        }
    }

    private fun backupCorruptSettings(): RuntimeSettings {
        val corrupt = settingsFile.resolveSibling("${settingsFile.fileName}.corrupt")
        runCatching { Files.move(settingsFile, corrupt, StandardCopyOption.REPLACE_EXISTING) }
        return defaultSettings()
    }

    fun loadSettings(): RuntimeSettings = synchronized(lock) {
        val defaults = defaultSettings()
        if (!Files.isRegularFile(settingsFile)) {
            PrivateFiles.atomicWriteUtf8(settingsFile, JsonCodec.encodePretty(diskPayload(defaults)))
            return defaults
        }
        val raw = try {
            JsonCodec.decodeMap(Files.readString(settingsFile, Charsets.UTF_8))
        } catch (_: Exception) {
            return backupCorruptSettings()
        }
        val rawApiUrl = (raw["api_url"] ?: "").toString().trim().trimEnd('/').ifEmpty { defaults.apiUrl }
        val apiUrl = runCatching { validateBrainUrl(rawApiUrl) }.getOrElse { defaults.apiUrl }
        RuntimeSettings(
            apiUrl = apiUrl,
            apiKey = memoryApiKey,
            turnDelay = normalizeTurnDelay(raw["turn_delay"]),
            burnClocks = JsonCodec.asBool(raw["burn_clocks"], false),
            cmConfig = normalizeCmConfig(raw["cm_config"]),
        )
    }

    fun saveSettings(settings: RuntimeSettings, persistApiKey: Boolean = true): RuntimeSettings = synchronized(lock) {
        val validUrl = validateBrainUrl(settings.apiUrl.ifBlank { defaultApiUrl() })
        val cleanKey = settings.apiKey.trim()
        val normalized = RuntimeSettings(
            apiUrl = validUrl,
            apiKey = cleanKey,
            turnDelay = normalizeTurnDelay(settings.turnDelay.toMap()),
            burnClocks = settings.burnClocks,
            cmConfig = normalizeCmConfig(settings.cmConfig),
        )
        memoryApiKey = cleanKey
        if (persistApiKey) {
            if (cleanKey.isNotEmpty()) {
                PrivateFiles.atomicWriteUtf8(apiKeyFile, "$cleanKey\n")
            } else {
                Files.deleteIfExists(apiKeyFile)
            }
        }
        PrivateFiles.atomicWriteUtf8(settingsFile, JsonCodec.encodePretty(diskPayload(normalized)))
        normalized
    }

    fun setBrainConfig(apiUrl: String, apiKey: String? = null): RuntimeSettings = synchronized(lock) {
        val cur = loadSettings()
        saveSettings(
            cur.copy(
                apiUrl = validateBrainUrl(apiUrl),
                apiKey = apiKey?.trim() ?: cur.apiKey,
            )
        )
    }

    fun setApiKey(apiKey: String) = synchronized(lock) {
        val clean = apiKey.trim()
        memoryApiKey = clean
        if (clean.isNotEmpty()) {
            PrivateFiles.atomicWriteUtf8(apiKeyFile, "$clean\n")
        } else {
            Files.deleteIfExists(apiKeyFile)
        }
    }

    fun setTurnDelay(minVal: Double, maxVal: Double, disabled: Boolean): TurnDelayConfig = synchronized(lock) {
        val cur = loadSettings()
        val prev = cur.turnDelay
        val nextDelay = if (disabled) {
            normalizeTurnDelay(
                mapOf(
                    "min" to 0.0,
                    "max" to 0.0,
                    "restore_min" to prev.restoreMin,
                    "restore_max" to prev.restoreMax,
                    "disabled" to true,
                )
            )
        } else {
            val lo = max(0.0, minVal.takeIf { it.isFinite() } ?: 1.6)
            val hi = max(lo, maxVal.takeIf { it.isFinite() } ?: 3.7)
            normalizeTurnDelay(
                mapOf(
                    "min" to lo,
                    "max" to hi,
                    "restore_min" to lo,
                    "restore_max" to hi,
                    "disabled" to false,
                )
            )
        }
        saveSettings(cur.copy(turnDelay = nextDelay)).turnDelay
    }

    fun setBurnClocks(burn: Boolean): RuntimeSettings = synchronized(lock) {
        val cur = loadSettings()
        saveSettings(cur.copy(burnClocks = burn))
    }

    fun setCmConfig(patch: Map<String, Any?>): LinkedHashMap<String, Any?> = synchronized(lock) {
        val cur = loadSettings()
        val merged = LinkedHashMap<String, Any?>(cur.cmConfig).apply { putAll(patch) }
        saveSettings(cur.copy(cmConfig = normalizeCmConfig(merged))).cmConfig
    }

    fun accountSalt(): String = synchronized(lock) {
        val envSalt = (System.getenv("SWEEPY_ACCOUNT_SALT") ?: "").trim()
        if (envSalt.length >= 32) return envSalt
        if (Files.isRegularFile(saltFile)) {
            val existing = runCatching { Files.readString(saltFile, Charsets.UTF_8).trim() }.getOrDefault("")
            if (existing.length >= 32) return existing
        }
        val salt = PrivateFiles.randomHex(32)
        PrivateFiles.atomicWriteUtf8(saltFile, "$salt\n")
        salt
    }

    fun loadOrCreatePersistentDeviceId(): String = synchronized(lock) {
        if (Files.isRegularFile(generatedDeviceIdFile)) {
            val existing = runCatching { Files.readString(generatedDeviceIdFile, Charsets.UTF_8).trim().lowercase() }
                .getOrDefault("")
            if (DeviceIdentity.isValidDeviceId(existing)) return existing
        }
        val fresh = PrivateFiles.randomHex(20)
        PrivateFiles.atomicWriteUtf8(generatedDeviceIdFile, "$fresh\n")
        fresh
    }

    fun saveRefreshToken(token: String) = synchronized(lock) {
        PrivateFiles.atomicWriteUtf8(refreshFile, "${token.trim()}\n")
    }

    fun readRefreshToken(): String? = synchronized(lock) {
        if (!Files.isRegularFile(refreshFile)) return null
        val text = Files.readString(refreshFile, Charsets.UTF_8).trim()
        text.ifEmpty { null }
    }

    fun clearCredentials(forgetApiKey: Boolean = false) = synchronized(lock) {
        Files.deleteIfExists(refreshFile)
        Files.deleteIfExists(deviceFile)
        if (forgetApiKey) {
            memoryApiKey = ""
            Files.deleteIfExists(apiKeyFile)
        }
    }
}

fun defaultDesktopRuntimeDir(): File {
    val xdg = System.getenv("XDG_DATA_HOME")
    val base = if (!xdg.isNullOrBlank()) File(xdg) else File(System.getProperty("user.home"), ".local/share")
    return File(base, "sweepy/uma_runtime")
}
