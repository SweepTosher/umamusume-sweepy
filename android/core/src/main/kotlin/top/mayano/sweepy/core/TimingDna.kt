package top.mayano.sweepy.core

import java.nio.file.Files
import java.nio.file.Path
import java.security.SecureRandom
import java.util.Random
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

class TimingDna(
    seedPath: Path,
    @Volatile var disabled: Boolean = false,
    @Volatile var turnMin: Double = 2.5,
    @Volatile var turnMax: Double = 5.0,
) {
    val seed: Long = loadOrCreateSeed(seedPath)
    private val rng = Random(seed)
    private val lock = Any()

    private val userSigma = randUniform(0.45, 0.75)
    private val userSpeedShift = randUniform(0.92, 1.08)
    private val userDistractionChance = randUniform(0.015, 0.065)
    private val userDistractionMin = randUniform(1.5, 3.5)
    private val userDistractionMax = randUniform(7.0, 14.0)
    private val endpointShifts: Map<String, Double> = BASE_DELAYS.keys.associateWith { randUniform(0.85, 1.15) }

    private fun randUniform(lo: Double, hi: Double): Double = synchronized(lock) {
        lo + (hi - lo) * rng.nextDouble()
    }

    private fun randGaussian(mean: Double, stddev: Double): Double = synchronized(lock) {
        mean + stddev * rng.nextGaussian()
    }

    private fun lognormal(mu: Double, sigma: Double): Double = synchronized(lock) {
        exp(mu + sigma * rng.nextGaussian())
    }

    fun sampleEndpointDelay(endpoint: String): Double {
        if (disabled) return 0.0
        val key = pacingName(endpoint)
        val triple = BASE_DELAYS[key]
        var dt = if (triple == null) {
            val targetDelay = 0.3 * userSpeedShift
            val mu = ln(targetDelay) - (userSigma * userSigma) / 2.0
            max(0.08, min(1.2, lognormal(mu, userSigma)))
        } else {
            val (realMin, realMax, realAvg) = triple
            val shift = endpointShifts[key] ?: 1.0
            val targetDelay = realAvg * userSpeedShift * shift
            val shiftedMin = realMin * userSpeedShift * shift
            val shiftedMax = realMax * userSpeedShift * shift
            val mu = ln(targetDelay) - (userSigma * userSigma) / 2.0
            max(shiftedMin, min(shiftedMax, lognormal(mu, userSigma)))
        }
        val roll = synchronized(lock) { rng.nextDouble() }
        if (roll < userDistractionChance) {
            dt += randUniform(userDistractionMin, userDistractionMax)
        }
        return dt
    }

    fun sampleTurnDelay(): Double {
        if (disabled) return 0.0
        val tMin = min(turnMin, turnMax)
        val tMax = max(turnMin, turnMax)
        val span = tMax - tMin
        val targetMean = (((tMin + tMax) / 2.0) + randUniform(-0.08, 0.08) * span) * userSpeedShift
        val sigma = 0.75 * userSigma
        val mu = ln(max(0.1, targetMean)) - (sigma * sigma) / 2.0
        val dt = lognormal(mu, sigma)
        return min(tMax * 5.0, max(tMin * 0.5, dt))
    }

    fun enforceFloorWaitMs(lastCallMonoMs: Long?, nowMonoMs: Long = System.nanoTime() / 1_000_000L): Long {
        if (lastCallMonoMs == null || lastCallMonoMs <= 0L) return 0L
        val elapsedSec = (nowMonoMs - lastCallMonoMs) / 1000.0
        val rem = HARD_CALL_FLOOR_SECONDS - elapsedSec
        return if (rem > 0.0) (rem * 1000.0).toLong().coerceAtLeast(1L) else 0L
    }

    fun makeRaceOutButtonInfo(
        viewerId: Long,
        scenarioId: Int,
        screenH: Int = 864,
        serverNowSec: Double? = null,
    ): String {
        require(viewerId > 0L) { "viewer_id must be positive" }
        require(scenarioId > 0) { "scenario_id must be positive" }

        val windowW = max(1, (screenH * 9) / 16)
        val scaleFactor = 1080.0 / windowW.toDouble()
        val refX = max(844, min(1150, randGaussian(991.0, 62.0).toInt()))
        val refY = max(55, min(255, randGaussian(144.0, 33.0).toInt()))

        val physicalX = (refX / scaleFactor).toInt()
        val physicalY = (refY / scaleFactor).toInt()

        val clickX = (physicalX * scaleFactor * 10000.0).toInt()
        val clickY = (physicalY * scaleFactor * 10000.0).toInt()

        val baseNow = serverNowSec ?: (System.currentTimeMillis() / 1000.0)
        val clickTs = (baseNow - randUniform(3.0, 4.5)).toLong()

        val payload = linkedMapOf<String, Any?>(
            "ViewerId" to viewerId,
            "DeviceId" to 4,
            "ScenarioId" to scenarioId,
            "ClickPosX" to clickX,
            "ClickPosY" to clickY,
            "ClickServerTime" to clickTs,
        )
        return JsonCodec.encode(payload)
    }

    companion object {
        const val HARD_CALL_FLOOR_SECONDS = 0.14
        const val DISABLED_SCHEDULER_YIELD_MS = 1L

        private val BASE_DELAYS: Map<String, Triple<Double, Double, Double>> = mapOf(
            "load_index" to Triple(1.16, 14.69, 5.26),
            "load_career" to Triple(0.62, 7.64, 2.56),
            "pre_single_mode" to Triple(1.80, 25.95, 2.03),
            "start_career" to Triple(1.58, 6.23, 1.98),
            "start_session" to Triple(0.62, 4.55, 1.06),
            "pre_signup" to Triple(0.62, 4.55, 1.06),
            "signup" to Triple(0.62, 4.55, 1.06),
            "check_event" to Triple(1.11, 3.90, 1.88),
            "continue" to Triple(0.96, 4.82, 3.05),
            "exec_command" to Triple(2.86, 17.68, 4.82),
            "finish_career" to Triple(3.05, 15.49, 3.54),
            "gain_skills" to Triple(7.02, 99.37, 54.62),
            "read_info" to Triple(1.16, 14.69, 5.26),
            "recovery_trainer_point" to Triple(0.62, 4.55, 1.06),
            "multi_item_exchange" to Triple(4.20, 13.79, 8.29),
            "multi_item_use" to Triple(2.99, 9.87, 5.67),
            "minigame_end" to Triple(1.11, 3.90, 1.88),
            "race_end" to Triple(1.85, 3.90, 2.01),
            "race_entry" to Triple(0.73, 4.94, 0.78),
            "change_running_style" to Triple(0.73, 4.94, 0.78),
            "reserve_race" to Triple(2.78, 9.26, 4.90),
            "race_out" to Triple(2.20, 9.91, 3.79),
            "race_start" to Triple(1.93, 10.36, 3.46),
        )

        private val PATH_TO_KEY = mapOf(
            "load/index" to "load_index",
            "read_info/index" to "read_info",
            "pre_single_mode/index" to "pre_single_mode",
            "tool/start_session" to "start_session",
            "tool/pre_signup" to "pre_signup",
            "tool/signup" to "signup",
            "user/recovery_trainer_point" to "recovery_trainer_point",
        )

        private val SCENARIO_PREFIXES = setOf(
            "single_mode", "single_mode_team", "single_mode_live", "single_mode_free"
        )

        private val SCENARIO_ALIASES = mapOf(
            "start" to "start_career",
            "load" to "load_career",
            "finish" to "finish_career",
            "race_continue" to "continue",
        )

        fun pacingName(endpoint: String): String {
            val clean = endpoint.trim().trim('/')
            if (clean in BASE_DELAYS) return clean
            PATH_TO_KEY[clean]?.let { return it }
            val idx = clean.lastIndexOf('/')
            if (idx > 0) {
                val prefix = clean.substring(0, idx)
                val op = clean.substring(idx + 1)
                if (prefix in SCENARIO_PREFIXES) {
                    return SCENARIO_ALIASES[op] ?: op
                }
            }
            return clean.substringAfterLast('/')
        }

        private fun loadOrCreateSeed(seedPath: Path): Long {
            val resolved = seedPath.toAbsolutePath().normalize()
            if (!Files.exists(resolved)) {
                val seed = 1_000_000L + SecureRandom().nextInt(9_000_000)
                PrivateFiles.atomicWriteUtf8(resolved, "$seed\n")
            }
            val text = Files.readString(resolved, Charsets.UTF_8).trim()
            val seed = text.toLongOrNull()
                ?: throw IllegalArgumentException("Invalid .timing_dna seed in $resolved")
            if (seed !in 1_000_000L..9_999_999L) {
                throw IllegalArgumentException("Timing DNA seed $seed must be a 7-digit integer")
            }
            return seed
        }
    }
}
