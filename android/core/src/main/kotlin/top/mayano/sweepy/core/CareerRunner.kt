package top.mayano.sweepy.core

import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import kotlin.math.min
import kotlin.math.roundToLong

private class StopCareerLoop : Throwable()

class CareerRunner(
    private val fastSleep: Boolean = false,
    accountSalt: String = "",
    runtimeDir: Path? = null,
    private val catalog: Catalog? = null,
    private val onRunningChanged: ((Boolean) -> Unit)? = null,
) {
    private val lock = ReentrantLock()
    private val stopRequested = AtomicBoolean(false)
    @Volatile private var workerThread: Thread? = null
    @Volatile private var stopLatch = CountDownLatch(0)
    private val accountSalt: String = accountSalt.trim()
    private val runtimeDir: Path? = runtimeDir?.toAbsolutePath()?.normalize()

    @Volatile var client: UmaClient? = null
    @Volatile var brain: BrainClient? = null
    @Volatile var burnClocks: Boolean = false
        private set
    private var cmOptions: LinkedHashMap<String, Any?>? = null

    private var _running: Boolean = false
    private var _finished: Boolean = false
    private var _stopped: Boolean = false
    private var _status: String = "idle"
    private var _error: String? = null
    private var _result: LinkedHashMap<String, Any?>? = null
    private var _latestAccountData: LinkedHashMap<String, Any?>? = null
    private var _latestAccountDataVersion: Int = 0
    private var _finalTurnPayload: LinkedHashMap<String, Any?>? = null
    private var _terminalSkillsBought: Boolean = false

    private var viewerIdHash: String = ""
    private val pendingDrainedStories = mutableListOf<Int>()
    private val pendingSettledRaces = mutableListOf<LinkedHashMap<String, Any?>>()
    private var lastCommand: LinkedHashMap<String, Any?>? = null
    private val rejectedPrograms = mutableListOf<List<Int>>()
    private val rejectedCommands = mutableListOf<List<Int>>()
    private val rejectedSquares = mutableListOf<List<Int>>()
    private var rejectedSquareBoard: SquareBoardSig? = null
    private var pendingSquareAttempt: SquareAttempt? = null
    private val commandAttempts = mutableListOf<List<Int>>()
    private var prevEndpointWasMasterSquare: Boolean = false
    private var resumePending: Boolean = false

    private var apiCalls: Int = 0
    private var clocksUsed: Int = 0
    private var alarmClockInventory: Int = 0
    private var lastAction: String = "IDLE"
    private var history = mutableListOf<LinkedHashMap<String, Any?>>()
    private var telemetryTurn: Int = 0
    private var telemetryPlayingState: Int = 0
    private var telemetryStats = defaultStats()
    private var telemetryTokens = defaultTokens()
    private var telemetrySongs = defaultSongs()

    private data class SquareBoardSig(
        val turn: Int,
        val playingState: Int,
        val offered: List<Pair<Int, Int>>,
    )

    private data class SquareStateSig(
        val turn: Int,
        val playingState: Int,
        val balances: List<Int>,
        val masterIds: List<Int>,
        val nextIds: List<Int>,
    )

    private data class SquareAttempt(
        val turn: Int,
        val squareId: Int,
        val playingState: Int,
        val board: SquareBoardSig,
        val state: SquareStateSig?,
    )

    val running: Boolean
        get() = lock.withLock { _running }

    val finished: Boolean
        get() = lock.withLock { _finished }

    val latestAccountData: LinkedHashMap<String, Any?>?
        get() = lock.withLock { _latestAccountData?.let { LinkedHashMap(it) } }

    fun latestAccountSnapshot(): Pair<LinkedHashMap<String, Any?>?, Int> = lock.withLock {
        val data = _latestAccountData?.let { LinkedHashMap(it) }
        data to _latestAccountDataVersion
    }

    fun setBurnClocks(enabled: Boolean) {
        lock.withLock {
            burnClocks = enabled
        }
    }

    fun setCmOptions(options: Map<String, Any?>?) {
        lock.withLock {
            cmOptions = options?.let { LinkedHashMap(it) }
        }
    }

    fun stop() {
        stopRequested.set(true)
        runCatching { brain?.close() }
        val latch = stopLatch
        val t = workerThread
        if (t != null && t.isAlive && t !== Thread.currentThread()) {
            runCatching { latch.await(5L, TimeUnit.SECONDS) }
        }
    }

    fun clearAccountData() {
        lock.withLock {
            _latestAccountData = null
            _latestAccountDataVersion += 1
        }
    }

    fun snapshot(): LinkedHashMap<String, Any?> = lock.withLock {
        linkedMapOf(
            "running" to _running,
            "finished" to _finished,
            "stopped" to _stopped,
            "status" to _status,
            "error" to _error,
            "last_error" to _error,
            "result" to _result?.let { LinkedHashMap(it) },
            "burn_clocks" to burnClocks,
            "turn" to telemetryTurn,
            "playing_state" to telemetryPlayingState,
            "stats" to LinkedHashMap(telemetryStats),
            "tokens" to LinkedHashMap(telemetryTokens),
            "songs" to LinkedHashMap(telemetrySongs),
            "api_calls" to apiCalls,
            "clocks_used" to clocksUsed,
            "last_action" to lastAction,
            "history" to history.map { LinkedHashMap(it) },
            "final_turn_export_ready" to (_finalTurnPayload != null),
            "cm_active" to JsonCodec.asBool(cmOptions?.get("cm_mode"), false),
        )
    }

    private fun captureFinalTurnExport(state: Map<String, Any?>) {
        val chara = JsonCodec.asMap(state["chara_info"])
        if (!UmaDumpExport.isFinalTurn(chara)) return
        val payload = UmaDumpExport.buildFinalTurnPayload(state) ?: return
        lock.withLock {
            _finalTurnPayload = payload
        }
    }

    fun finalTurnExport(): LinkedHashMap<String, Any?>? {
        val payload = lock.withLock { _finalTurnPayload } ?: return null
        val chara = JsonCodec.asMap(payload["chara_info"])
        return linkedMapOf(
            "json" to payload,
            "filename" to UmaDumpExport.exportFilename(chara),
            "turn" to chara?.get("turn"),
        )
    }

    fun start(
        client: UmaClient,
        brain: BrainClient,
        burnClocks: Boolean = false,
        cmOptions: Map<String, Any?>? = null,
        initialState: Map<String, Any?>? = null,
        accountData: Map<String, Any?>? = null,
        maxSteps: Int = 1200,
    ) {
        if (brain.apiKey.trim().isEmpty()) {
            throw BrainApiException("Brain API key is required to run a career")
        }
        val latch: CountDownLatch
        lock.withLock {
            val t = workerThread
            if (_running && t != null && t.isAlive) {
                throw IllegalStateException("Runner already running")
            }
            resetRunState(burnClocks = burnClocks, cmOptions = cmOptions)
            _running = true
            _status = "running"
            latch = CountDownLatch(1)
            stopLatch = latch
        }
        onRunningChanged?.invoke(true)
        val t = Thread(
            {
                try {
                    workerEntry(
                        umaClient = client,
                        brainClient = brain,
                        initialState = initialState,
                        accountData = accountData,
                        maxSteps = maxSteps,
                    )
                } finally {
                    latch.countDown()
                }
            },
            "sweepy-career-runner",
        ).apply {
            isDaemon = true
            start()
        }
        workerThread = t
    }

    fun runSync(
        client: UmaClient,
        brain: BrainClient,
        burnClocks: Boolean = false,
        cmOptions: Map<String, Any?>? = null,
        initialState: Map<String, Any?>? = null,
        accountData: Map<String, Any?>? = null,
        maxSteps: Int = 1200,
    ): LinkedHashMap<String, Any?> {
        if (brain.apiKey.trim().isEmpty()) {
            throw BrainApiException("Brain API key is required to run a career")
        }
        val latch = CountDownLatch(1)
        lock.withLock {
            if (_running) throw IllegalStateException("Runner already running")
            resetRunState(burnClocks = burnClocks, cmOptions = cmOptions)
            _running = true
            _status = "running"
            stopLatch = latch
        }
        onRunningChanged?.invoke(true)
        try {
            workerEntry(
                umaClient = client,
                brainClient = brain,
                initialState = initialState,
                accountData = accountData,
                maxSteps = maxSteps,
            )
        } finally {
            latch.countDown()
        }
        return snapshot()
    }

    private fun resetRunState(burnClocks: Boolean, cmOptions: Map<String, Any?>?) {
        stopRequested.set(false)
        this.burnClocks = burnClocks
        this.cmOptions = cmOptions?.let { LinkedHashMap(it) }
        _finished = false
        _stopped = false
        _error = null
        _result = null
        _latestAccountData = null
        _finalTurnPayload = null
        _terminalSkillsBought = false
        pendingDrainedStories.clear()
        pendingSettledRaces.clear()
        lastCommand = null
        rejectedPrograms.clear()
        rejectedCommands.clear()
        rejectedSquares.clear()
        rejectedSquareBoard = null
        pendingSquareAttempt = null
        commandAttempts.clear()
        prevEndpointWasMasterSquare = false
        resumePending = false
        apiCalls = 0
        clocksUsed = 0
        alarmClockInventory = 0
        lastAction = "STARTING"
        history.clear()
        telemetryTurn = 0
        telemetryPlayingState = 0
        telemetryStats = defaultStats()
        telemetryTokens = defaultTokens()
        telemetrySongs = defaultSongs()
    }

    private fun checkStop() {
        if (stopRequested.get()) throw StopCareerLoop()
    }

    private fun sleepFixed(seconds: Double) {
        checkStop()
        if (fastSleep || seconds <= 0.0) return
        val timing = client?.timing
        if (timing != null && timing.disabled && seconds < 0.15) return
        val endMs = (System.nanoTime() / 1_000_000L) + (seconds * 1000.0).roundToLong()
        while (true) {
            checkStop()
            val rem = endMs - (System.nanoTime() / 1_000_000L)
            if (rem <= 0L) break
            Thread.sleep(min(50L, rem))
        }
    }

    private fun sleepTurnPacing() {
        checkStop()
        if (fastSleep) return
        val timing = client?.timing ?: return
        if (!timing.disabled) {
            sleepFixed(timing.sampleTurnDelay())
        }
    }

    private fun rpc(endpoint: String, payload: Map<String, Any?> = emptyMap()): LinkedHashMap<String, Any?> {
        checkStop()
        lock.withLock { apiCalls += 1 }
        val c = client ?: throw IllegalStateException("Client not initialized")
        return c.call(endpoint, payload)
    }

    private fun loadCareer(scenarioId: Int = 3): LinkedHashMap<String, Any?> {
        checkStop()
        lock.withLock { apiCalls += 1 }
        val c = client ?: throw IllegalStateException("Client not initialized")
        return c.loadCareer(scenarioId)
    }

    private fun recordHistory(turn: Int, kind: String, action: String, detail: String = "") {
        lock.withLock {
            lastAction = action
            val tsSec = Math.round((System.currentTimeMillis() / 1000.0) * 1000.0) / 1000.0
            history.add(
                linkedMapOf(
                    "turn" to turn,
                    "kind" to kind,
                    "type" to kind,
                    "action" to action,
                    "detail" to detail,
                    "snapshot" to detail,
                    "ts" to tsSec,
                )
            )
            if (history.size > 80) {
                history = history.subList(history.size - 80, history.size).toMutableList()
            }
        }
    }

    private fun autobuySkillsEnabled(): Boolean {
        if (runtimeDir != null) {
            val flagPath = runtimeDir.resolve(AUTOBUY_SKILLS_FLAG)
            if (Files.isRegularFile(flagPath)) {
                return runCatching {
                    Files.readString(flagPath, Charsets.UTF_8).trim().lowercase() in ON_VALUES
                }.getOrDefault(false)
            }
        }
        return (System.getenv(AUTOBUY_SKILLS_ENV) ?: "0").trim().lowercase() in ON_VALUES
    }

    private fun terminalSkillBundle(chara: Map<String, Any?>?): List<Map<String, Int>> {
        val shop = catalog?.skillShop ?: return emptyList()
        return shop.bundle(chara)
    }

    private fun isMasterSquarePhase(state: Map<String, Any?>): Boolean {
        val chara = JsonCodec.asMap(state["chara_info"]) ?: return false
        return JsonCodec.asInt(chara["playing_state"], 0) == 10
    }

    private fun squareBoardSignature(state: Map<String, Any?>): SquareBoardSig {
        val chara = JsonCodec.asMap(state["chara_info"]) ?: emptyMap()
        val live = JsonCodec.asMap(state["live_data_set"]) ?: emptyMap()
        val turn = JsonCodec.asInt(chara["turn"], lock.withLock { telemetryTurn })
        val playingState = JsonCodec.asInt(chara["playing_state"], 0)
        val board = JsonCodec.asList(live["next_square_info_array"]) ?: emptyList()
        val offered = mutableListOf<Pair<Int, Int>>()
        for (item in board) {
            val row = JsonCodec.asMap(item) ?: continue
            offered.add(JsonCodec.asInt(row["square_id"], 0) to JsonCodec.asInt(row["square_num"], 0))
        }
        return SquareBoardSig(turn, playingState, offered)
    }

    private fun squareStateSignature(state: Map<String, Any?>): SquareStateSig? {
        val chara = JsonCodec.asMap(state["chara_info"]) ?: emptyMap()
        val live = JsonCodec.asMap(state["live_data_set"]) ?: return null
        val perf = JsonCodec.asMap(live["live_performance_info"]) ?: return null
        val keys = listOf("dance", "passion", "vocal", "visual", "mental")
        val balances = mutableListOf<Int>()
        for (k in keys) {
            val v = JsonCodec.asLongOrNull(perf[k]) ?: return null
            balances.add(v.toInt())
        }
        fun songIds(key: String): List<Int> {
            val vals = JsonCodec.asList(live[key]) ?: return emptyList()
            return vals.mapNotNull { JsonCodec.asLongOrNull(it)?.toInt() }.distinct().sorted()
        }
        return SquareStateSig(
            turn = JsonCodec.asInt(chara["turn"], lock.withLock { telemetryTurn }),
            playingState = JsonCodec.asInt(chara["playing_state"], 0),
            balances = balances,
            masterIds = songIds("master_live_id_array"),
            nextIds = songIds("next_live_id_array"),
        )
    }

    private fun syncRejectedSquares(state: Map<String, Any?>) {
        if (rejectedSquares.isNotEmpty() && (!isMasterSquarePhase(state) || rejectedSquareBoard != squareBoardSignature(state))) {
            rejectedSquares.clear()
            rejectedSquareBoard = null
        }
    }

    private fun reconcileRejectedSquare(exc: StateRecoveryException, state: Map<String, Any?>) {
        val attempt = pendingSquareAttempt
        pendingSquareAttempt = null
        if (attempt == null) return
        if (exc.endpoint != "single_mode_live/master_square") return
        if (exc.ambiguous || exc.code == null) return
        if (attempt.playingState != 10 || !isMasterSquarePhase(state)) return
        if (attempt.turn <= 0 || attempt.squareId <= 0) return
        if (attempt.board.offered.isEmpty()) return
        if (attempt.board.offered.none { it.first == attempt.squareId }) return
        if (squareBoardSignature(state) != attempt.board) return
        val beforeState = attempt.state ?: return
        if (squareStateSignature(state) != beforeState) return
        val pair = listOf(attempt.turn, attempt.squareId)
        if (rejectedSquareBoard != attempt.board) {
            rejectedSquares.clear()
            rejectedSquareBoard = attempt.board
        }
        if (pair !in rejectedSquares) {
            rejectedSquares.add(pair)
            trimPairList(rejectedSquares, 32)
        }
    }

    private fun buyTerminalSkills(state: LinkedHashMap<String, Any?>) {
        val chara = JsonCodec.asMap(state["chara_info"]) ?: return
        if (JsonCodec.asInt(chara["skill_point"], 0) <= 0) return
        val finished = JsonCodec.asMap(state["single_mode_finish_common"]) != null
        val turn = JsonCodec.asInt(chara["turn"], 0)
        val playingState = JsonCodec.asInt(chara["playing_state"], 0)
        val pendingEvents = !JsonCodec.asList(state["unchecked_event_array"]).isNullOrEmpty()
        val atFinishScreen = turn >= UmaDumpExport.FINAL_CAREER_TURN && playingState == 5 && !pendingEvents
        if (!finished && !atFinishScreen && turn <= UmaDumpExport.FINAL_CAREER_TURN) return
        val bundle = terminalSkillBundle(chara)
        if (bundle.isEmpty()) {
            _terminalSkillsBought = true
            return
        }
        executeRpcStep(
            linkedMapOf(
                "endpoint" to "single_mode_live/gain_skills",
                "payload" to linkedMapOf(
                    "gain_skill_info_array" to bundle,
                    "current_turn" to turn,
                ),
            ),
            state,
        )
        _terminalSkillsBought = true
    }

    private fun updateTelemetry(state: Map<String, Any?>) {
        captureFinalTurnExport(state)
        val chara = JsonCodec.asMap(state["chara_info"])
        val live = JsonCodec.asMap(state["live_data_set"])
        lock.withLock {
            if (chara != null) {
                telemetryTurn = JsonCodec.asInt(chara["turn"], 0)
                telemetryPlayingState = JsonCodec.asInt(chara["playing_state"], 0)
                telemetryStats = linkedMapOf(
                    "hp" to JsonCodec.asInt(chara["vital"], 0),
                    "max_hp" to JsonCodec.asInt(chara["max_vital"], 100),
                    "mood" to JsonCodec.asInt(chara["motivation"], 3),
                    "speed" to JsonCodec.asInt(chara["speed"], 0),
                    "stamina" to JsonCodec.asInt(chara["stamina"], 0),
                    "power" to JsonCodec.asInt(chara["power"], 0),
                    "guts" to JsonCodec.asInt(chara["guts"], 0),
                    "wit" to JsonCodec.asInt(chara["wiz"], 0),
                    "sp" to JsonCodec.asInt(chara["skill_point"], 0),
                    "fans" to JsonCodec.asInt(chara["fans"], 0),
                )
            }
            if (live != null) {
                val perf = JsonCodec.asMap(live["live_performance_info"])
                if (perf != null) {
                    telemetryTokens = linkedMapOf(
                        "da" to JsonCodec.asInt(perf["dance"], 0),
                        "pa" to JsonCodec.asInt(perf["passion"], 0),
                        "vo" to JsonCodec.asInt(perf["vocal"], 0),
                        "vi" to JsonCodec.asInt(perf["visual"], 0),
                        "me" to JsonCodec.asInt(perf["mental"], 0),
                    )
                }
                telemetrySongs = linkedMapOf(
                    "mastered" to (JsonCodec.asList(live["master_live_id_array"])?.size ?: 0),
                    "staged" to (JsonCodec.asList(live["next_live_id_array"])?.size ?: 0),
                    "concerts_done" to (JsonCodec.asList(live["live_result_array"])?.size ?: 0),
                )
            }
        }
    }

    private fun bootstrapOrResumeState(
        initialState: Map<String, Any?>?,
        accountData: Map<String, Any?>?,
    ): LinkedHashMap<String, Any?> {
        if (initialState != null) {
            val normalized = normalizeCareerState(unwrapEnvelope(initialState))
            updateTelemetry(normalized)
            return normalized
        }

        val acct = if (accountData != null) {
            unwrapEnvelope(accountData)
        } else {
            lock.withLock { apiCalls += 1 }
            val c = client ?: throw IllegalStateException("Client not initialized")
            unwrapEnvelope(c.login(readInfo = false))
        }

        lock.withLock {
            _latestAccountData = LinkedHashMap(acct)
            _latestAccountDataVersion += 1
        }

        alarmClockInventory = Catalog.itemCount(acct["item_list"] ?: acct["user_item_array"], 95)
        val activeLight = JsonCodec.asMap(acct["single_mode_chara_light"] ?: acct["single_mode_chara"])
        if (activeLight != null && JsonCodec.asLong(activeLight["single_mode_chara_id"], 0L) > 0L) {
            val activeScen = JsonCodec.asInt(activeLight["scenario_id"], 3)
            if (activeScen != 3) {
                throw IllegalStateException("Career scenario $activeScen, not Grand Live (3)")
            }
            val loaded = normalizeCareerState(unwrapEnvelope(loadCareer(3)))
            updateTelemetry(loaded)
            val turn = JsonCodec.asInt(JsonCodec.asMap(loaded["chara_info"])?.get("turn"), 1)
            recordHistory(turn, "Resume", "Resumed active Grand Live career", "Turn $turn")
            return loaded
        }

        throw IllegalStateException("no active career (start one in-game)")
    }

    private fun drainSingleChoiceEvents(state: LinkedHashMap<String, Any?>): Boolean {
        for (ignored in 0 until 64) {
            checkStop()
            val events = JsonCodec.asList(state["unchecked_event_array"]) ?: emptyList()
            if (events.isEmpty()) return false
            val ev = JsonCodec.asMap(events[0]) ?: return false
            val choices = eventChoices(ev)
            if (choices.size > 1) return true
            val turn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), 1)
            val eventId = strictPositiveInt(ev["event_id"])
                ?: throw IllegalStateException("Queued event has no usable event_id: ${ev["event_id"]}")
            val charaId = nonNegativeIntOrZero(ev["chara_id"])
            val storyId = nonNegativeIntOrNull(ev["story_id"])
            val res = rpc(
                "single_mode_live/check_event",
                linkedMapOf(
                    "event_id" to eventId,
                    "chara_id" to charaId,
                    "choice_number" to 0,
                    "current_turn" to turn,
                ),
            )
            mergeCareerState(state, unwrapEnvelope(res))
            if (storyId != null) pendingDrainedStories.add(storyId)
            updateTelemetry(state)
        }
        throw IllegalStateException("64 undrained single-choice events in a row")
    }

    private fun setViewerHash(c: UmaClient) {
        val rawVid = c.viewerId.toString().trim()
        if (rawVid.isEmpty() || rawVid == "0") {
            throw IllegalStateException("Client viewer identity is unavailable")
        }
        val material = if (accountSalt.isNotEmpty()) "$accountSalt:$rawVid" else rawVid
        val digest = MessageDigest.getInstance("SHA-256").digest(material.toByteArray(Charsets.UTF_8))
        viewerIdHash = UmaCrypto.bytesToHex(digest)
    }

    private fun clocksBudget(state: Map<String, Any?>): Pair<Int, Int> {
        val home = JsonCodec.asMap(state["home_info"]) ?: emptyMap()
        val freeClocks = JsonCodec.asInt(home["available_free_continue_num"], 0).coerceAtLeast(0)
        val rawAvail = home["available_continue_num"]
        val totalAvail = if (rawAvail != null && rawAvail !is Boolean && JsonCodec.asLongOrNull(rawAvail) != null) {
            JsonCodec.asInt(rawAvail, 0).coerceAtLeast(0)
        } else {
            (freeClocks + alarmClockInventory).coerceAtLeast(0)
        }
        return totalAvail to freeClocks
    }

    private fun reloadCareerState(
        state: LinkedHashMap<String, Any?>,
        clearReward: Boolean = false,
        resetMasterSquare: Boolean = true,
        updateTelemetryFlag: Boolean = true,
    ): LinkedHashMap<String, Any?> {
        val loaded = normalizeCareerState(unwrapEnvelope(loadCareer(3)))
        state.clear()
        state.putAll(loaded)
        if (clearReward) state.remove("race_reward_info")
        if (resetMasterSquare) prevEndpointWasMasterSquare = false
        if (updateTelemetryFlag) updateTelemetry(state)
        return loaded
    }

    private fun recordRejectedProgram(turn: Int, pid: Int) {
        if (pid <= 0) return
        val pair = listOf(turn, pid)
        if (pair !in rejectedPrograms) {
            rejectedPrograms.add(pair)
            trimPairList(rejectedPrograms, 32)
        }
    }

    private fun executeRaceMacro(op: String, params: Map<String, Any?>, state: LinkedHashMap<String, Any?>) {
        val chara = JsonCodec.asMap(state["chara_info"]) ?: emptyMap()
        var turn = JsonCodec.asInt(chara["turn"], JsonCodec.asInt(params["current_turn"], 1))
        var pid = JsonCodec.asInt(
            params["program_id"]
                ?: JsonCodec.asMap(state["race_start_info"])?.get("program_id")
                ?: chara["race_program_id"],
            0,
        )
        val mandatory = JsonCodec.asBool(params["mandatory"], false)
        val targetRank = JsonCodec.asInt(params["target_rank"], 18)
        var phase = (params["phase"] ?: "start").toString().ifBlank { "start" }

        if (op == "race_macro") {
            if (pid <= 0) throw BrainApiException("race_macro missing positive program_id")
            if (listOf(turn, pid) in rejectedPrograms) {
                recordHistory(turn, "Race", "Program $pid already raced this turn", "Skipped")
                return
            }
            state.remove("race_reward_info")
            val liveRsi = JsonCodec.asMap(state["race_start_info"])
            val livePid = JsonCodec.asInt(liveRsi?.get("program_id"), 0)
            val entryRes: LinkedHashMap<String, Any?>? = if (pid > 0 && livePid == pid) {
                recordHistory(turn, "Race", "Program $pid already entered", "Starting")
                null
            } else {
                try {
                    rpc("single_mode_live/race_entry", linkedMapOf("program_id" to pid, "current_turn" to turn))
                } catch (exc: StateRecoveryException) {
                    if (exc.code != 102 && exc.code != 205) throw exc
                    recordHistory(turn, "Race", "Program $pid was already entered", "Starting directly")
                    null
                }
            }
            if (entryRes != null) {
                mergeCareerState(state, unwrapEnvelope(entryRes))
                updateTelemetry(state)
                if (drainSingleChoiceEvents(state)) {
                    recordHistory(turn, "Race", "Entered race $pid (awaiting pre-race choice)", "Multi-choice")
                    return
                }
            }
            phase = "start"
        }

        if (op == "race_resume_macro") {
            if (drainSingleChoiceEvents(state)) return
        }

        var rank = 1
        val smCid = JsonCodec.asLong(JsonCodec.asMap(state["chara_info"])?.get("single_mode_chara_id"), 0L)

        if (phase == "start") {
            val startRes: LinkedHashMap<String, Any?> = try {
                rpc("single_mode_live/race_start", linkedMapOf("is_short" to 1, "current_turn" to turn))
            } catch (exc: StateRecoveryException) {
                when (exc.code) {
                    102 -> linkedMapOf("data" to reloadCareerState(state))
                    205 -> {
                        reloadCareerState(state)
                        val curTurn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), turn)
                        recordRejectedProgram(curTurn, pid)
                        recordHistory(curTurn, "Race", "Program $pid refused to start (205)", "Reloaded")
                        return
                    }
                    else -> throw exc
                }
            }
            val startData = unwrapEnvelope(startRes)
            mergeCareerState(state, startData)
            val rsi = JsonCodec.asMap(startData["race_start_info"]) ?: JsonCodec.asMap(state["race_start_info"]) ?: emptyMap()
            if (pid <= 0 && JsonCodec.asInt(rsi["program_id"], 0) > 0) {
                pid = JsonCodec.asInt(rsi["program_id"], 0)
            }
            val horses = JsonCodec.asList(rsi["race_horse_data"])
            val scenarioB64 = startData["race_scenario"] as? String
            if (scenarioB64 != null && horses != null && smCid > 0L) {
                rank = RaceDecoder.decodePlayerRank(scenarioB64, horses, smCid)
            }

            val clockLimit = if (burnClocks) 1 else targetRank
            if ((mandatory || burnClocks) && rank > clockLimit && clocksBudget(state).first > 0) {
                val fresh = normalizeCareerState(unwrapEnvelope(loadCareer(3)))
                JsonCodec.asMap(fresh["home_info"])?.let { state["home_info"] = it }
            }
            var (clocksAvailable, freeClocks) = clocksBudget(state)
            var refusedOnce = false
            while ((mandatory || burnClocks) && rank > clockLimit && clocksAvailable > 0) {
                val contType = if (freeClocks > 0) 1 else 2
                val contRes = try {
                    rpc(
                        "single_mode_live/continue",
                        linkedMapOf("current_turn" to turn, "continue_type" to contType),
                    )
                } catch (exc: StateRecoveryException) {
                    if (exc.code != 205) throw exc
                    reloadCareerState(state)
                    val curTurn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), turn)
                    recordRejectedProgram(curTurn, pid)
                    turn = curTurn
                    if (state["race_start_info"] == null) return
                    if (refusedOnce) break
                    refusedOnce = true
                    val nextBudget = clocksBudget(state)
                    clocksAvailable = nextBudget.first
                    freeClocks = nextBudget.second
                    continue
                }
                lock.withLock { clocksUsed += 1 }
                if (contType == 1) {
                    freeClocks = (freeClocks - 1).coerceAtLeast(0)
                } else {
                    alarmClockInventory = (alarmClockInventory - 1).coerceAtLeast(0)
                }
                clocksAvailable -= 1

                val contData = unwrapEnvelope(contRes)
                mergeCareerState(state, contData)
                if (JsonCodec.asMap(contData["home_info"]) != null) {
                    val refreshedBudget = clocksBudget(state)
                    clocksAvailable = refreshedBudget.first
                    freeClocks = refreshedBudget.second
                }

                if (drainSingleChoiceEvents(state)) return

                val retryRes = rpc("single_mode_live/race_start", linkedMapOf("is_short" to 1, "current_turn" to turn))
                val retryData = unwrapEnvelope(retryRes)
                mergeCareerState(state, retryData)
                val rRsi = JsonCodec.asMap(retryData["race_start_info"]) ?: JsonCodec.asMap(state["race_start_info"]) ?: emptyMap()
                val rHorses = JsonCodec.asList(rRsi["race_horse_data"])
                val rScen = retryData["race_scenario"] as? String
                if (rScen != null && rHorses != null && smCid > 0L) {
                    rank = RaceDecoder.decodePlayerRank(rScen, rHorses, smCid)
                }
                val curClocks = lock.withLock { clocksUsed }
                recordHistory(turn, "Race", "Clock used · retry $curClocks", "Program $pid · rank $rank")
            }
            phase = "end"
        }

        var resultRank = rank
        if (phase == "end") {
            sleepFixed(0.16)
            val endRes = try {
                rpc("single_mode_live/race_end", linkedMapOf("current_turn" to turn))
            } catch (exc: StateRecoveryException) {
                if (exc.code != 102) throw exc
                val loaded = reloadCareerState(state)
                if (state["race_start_info"] == null && state["race_reward_info"] == null) {
                    val curTurn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), turn)
                    recordRejectedProgram(curTurn, pid)
                    recordHistory(curTurn, "Race", "Program $pid already settled (102)", "Skipped")
                    return
                }
                linkedMapOf("data" to loaded)
            }
            val endData = unwrapEnvelope(endRes)
            mergeCareerState(state, endData)
            val rewardInfo = JsonCodec.asMap(endData["race_reward_info"])
            if (rewardInfo != null && rewardInfo["result_rank"] != null) {
                resultRank = JsonCodec.asInt(rewardInfo["result_rank"], resultRank)
            }
            phase = "out"
        }

        if (phase == "out") {
            val outRes = try {
                rpc("single_mode_live/race_out", linkedMapOf("current_turn" to turn))
            } catch (exc: StateRecoveryException) {
                if (exc.code != 102 && exc.code != 205) throw exc
                reloadCareerState(state, clearReward = true)
                val curTurn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), turn)
                recordRejectedProgram(curTurn, pid)
                recordHistory(curTurn, "Race", "Program $pid already out", "Reloaded")
                return
            }
            mergeCareerState(state, unwrapEnvelope(outRes), clearRace = true)
            val rewardInfo = JsonCodec.asMap(state["race_reward_info"])
            if (rewardInfo != null && rewardInfo["result_rank"] != null) {
                resultRank = JsonCodec.asInt(rewardInfo["result_rank"], resultRank)
            }
            state.remove("race_reward_info")
            recordRejectedProgram(turn, pid)
            if (pid > 0) {
                pendingSettledRaces.add(
                    linkedMapOf(
                        "turn" to turn,
                        "program_id" to pid,
                        "result_rank" to resultRank,
                    )
                )
            }
            recordHistory(turn, "Race", "Program $pid finished P$resultRank", "Rank $resultRank")
            val hasMulti = drainSingleChoiceEvents(state)
            val postTurn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), 0)
            if (!hasMulti && postTurn <= turn) {
                reloadCareerState(state, clearReward = true)
            } else {
                updateTelemetry(state)
            }
        }
    }

    private fun executeRpcStep(params: Map<String, Any?>, state: LinkedHashMap<String, Any?>) {
        val endpoint = (params["endpoint"] ?: "").toString().trim()
        val payload = LinkedHashMap<String, Any?>(JsonCodec.asMap(params["payload"]) ?: emptyMap())
        if (endpoint.isEmpty()) throw BrainApiException("rpc_step missing endpoint")
        val turn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), JsonCodec.asInt(payload["current_turn"], 1))

        if (endpoint.endsWith("/master_square")) {
            if (prevEndpointWasMasterSquare) sleepFixed(0.08)
            syncRejectedSquares(state)
            val prevLive = JsonCodec.asMap(state["live_data_set"])
            val rawBeforeArr = if (prevLive != null && prevLive["master_live_id_array"] != null) {
                JsonCodec.asList(prevLive["master_live_id_array"])
            } else {
                null
            }
            val beforeSongs = rawBeforeArr?.mapNotNull { JsonCodec.asLongOrNull(it)?.toInt() }?.toSet()
            val prevMastered = lock.withLock { telemetrySongs["mastered"] ?: 0 }
            pendingSquareAttempt = if (isMasterSquarePhase(state)) {
                SquareAttempt(
                    turn = turn,
                    squareId = JsonCodec.asInt(payload["square_id"], 0),
                    playingState = 10,
                    board = squareBoardSignature(state),
                    state = squareStateSignature(state),
                )
            } else {
                null
            }
            val res = rpc(endpoint, payload)
            pendingSquareAttempt = null
            rejectedSquares.clear()
            rejectedSquareBoard = null
            mergeCareerState(state, unwrapEnvelope(res))
            reloadCareerState(state, resetMasterSquare = false)
            prevEndpointWasMasterSquare = true

            val sqId = payload["square_id"]?.toString() ?: ""
            val afterArr = JsonCodec.asList(JsonCodec.asMap(state["live_data_set"])?.get("master_live_id_array")) ?: emptyList()
            val afterSongs = afterArr.mapNotNull { JsonCodec.asLongOrNull(it)?.toInt() }.toSet()
            val gained = if (beforeSongs != null) (afterSongs - beforeSongs).sorted() else emptyList()
            val masteredNow = lock.withLock { telemetrySongs["mastered"] ?: 0 }
            val isSong = if (beforeSongs != null) gained.isNotEmpty() else masteredNow > prevMastered

            val lesson = JsonCodec.asMap(params["lesson"]) ?: emptyMap()
            val lessonKind = (lesson["kind"] ?: "").toString().trim().lowercase()
            val lessonLabel = (lesson["label"] ?: "").toString().trim()
            val lessonDetail = (lesson["detail"] ?: "").toString().trim()
            if (lessonLabel.isNotEmpty()) {
                val historyKind = if (isSong || lessonKind == "song") "Song" else "Lesson"
                val label = if (historyKind == "Song" && gained.isNotEmpty()) "$lessonLabel ${gained[0]}" else lessonLabel
                val detail = if (lessonDetail.isNotEmpty()) "$lessonDetail · Songs: $masteredNow" else "Songs: $masteredNow"
                val action = if (lessonDetail.isNotEmpty()) "$label · slot $sqId · $lessonDetail" else "$label · slot $sqId"
                recordHistory(turn, historyKind, action, detail)
            } else if (isSong) {
                val label = if (gained.isNotEmpty()) "Learned song ${gained[0]}" else "Learned song"
                recordHistory(turn, "Song", "$label · slot $sqId", "Songs: $masteredNow")
            } else {
                recordHistory(turn, "Lesson", "Technique lesson · slot $sqId", "Songs: $masteredNow")
            }
            return
        }

        if (endpoint.endsWith("/gain_skills")) {
            val rawArr = JsonCodec.asList(payload["gain_skill_info_array"])
                ?: JsonCodec.asList(payload["skill_select_array"])
                ?: JsonCodec.asList(payload["skill_Select_array"])
                ?: emptyList()
            val skillItems = rawArr.mapNotNull { item ->
                val row = JsonCodec.asMap(item) ?: return@mapNotNull null
                val sid = JsonCodec.asInt(row["skill_id"], 0)
                if (sid <= 0) return@mapNotNull null
                val lvl = JsonCodec.asInt(row["level"] ?: row["skill_level"], 1)
                linkedMapOf<String, Any?>("skill_id" to sid, "level" to lvl)
            }
            if (skillItems.isEmpty()) throw BrainApiException("gain_skills missing skill items")
            val reqTurn = JsonCodec.asInt(payload["current_turn"], turn)
            val c = client ?: throw IllegalStateException("Client not initialized")
            val res = c.gainSkills(skillItems, reqTurn)
            mergeCareerState(state, unwrapEnvelope(res))
            reloadCareerState(state)
            val sidsStr = skillItems.joinToString(", ") { it["skill_id"].toString() }
            val label = if (skillItems.size == 1) "Learned skill $sidsStr" else "Learned ${skillItems.size} skills ($sidsStr)"
            val spLeft = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("skill_point"), 0)
            recordHistory(turn, "Skill", label, "SP left: $spLeft")
            return
        }

        prevEndpointWasMasterSquare = false

        if (endpoint.endsWith("/load")) {
            reloadCareerState(state, resetMasterSquare = false)
            return
        }

        if (endpoint.endsWith("/exec_command")) {
            val rawCmdId = JsonCodec.asInt(payload["command_id"], 0)
            val effCmdId = if (rawCmdId != 0) rawCmdId else JsonCodec.asInt(payload["command_group_id"], 0)
            val partners = mutableListOf<Int>()
            val cmdArray = JsonCodec.asList(JsonCodec.asMap(state["home_info"])?.get("command_info_array"))
                ?: JsonCodec.asList(JsonCodec.asMap(state["live_data_set"])?.get("command_info_array"))
                ?: emptyList()
            for (item in cmdArray) {
                val row = JsonCodec.asMap(item) ?: continue
                val rowCid = JsonCodec.asInt(row["command_id"], -1)
                if (rowCid == rawCmdId || rowCid == effCmdId) {
                    val pList = JsonCodec.asList(row["training_partner_array"]) ?: emptyList()
                    for (p in pList) {
                        JsonCodec.asLongOrNull(p)?.let { partners.add(it.toInt()) }
                    }
                    break
                }
            }
            sleepTurnPacing()
            val res = try {
                rpc(endpoint, payload)
            } catch (exc: StateRecoveryException) {
                val code = exc.code
                if (code != 205 && code != 2501) throw exc
                val sameTurnCount = commandAttempts.count { it[0] == turn }
                if (sameTurnCount >= 3) throw exc
                commandAttempts.add(listOf(turn, effCmdId))
                trimPairList(commandAttempts, 64)
                reloadCareerState(state)
                val pair = listOf(turn, effCmdId)
                if (pair !in rejectedCommands) {
                    rejectedCommands.add(pair)
                    trimPairList(rejectedCommands, 32)
                }
                recordHistory(turn, "Recovery", "Command $effCmdId refused by the server ($code)", "Reloaded")
                return
            }
            val resData = unwrapEnvelope(res)
            val cmdRes = JsonCodec.asMap(resData["command_result"]) ?: emptyMap()
            lastCommand = linkedMapOf(
                "turn" to turn,
                "command_id" to JsonCodec.asInt(cmdRes["command_id"], effCmdId),
                "result_state" to JsonCodec.asInt(cmdRes["result_state"], 0),
                "partners" to partners,
            )
            mergeCareerState(state, resData)
            if (JsonCodec.asMap(state["home_info"]) == null || JsonCodec.asMap(state["chara_info"]) == null) {
                reloadCareerState(state, updateTelemetryFlag = false)
            }
            prevEndpointWasMasterSquare = false
            updateTelemetry(state)
            val label = COMMAND_LABELS[effCmdId] ?: "Command $effCmdId"
            val st = lock.withLock { LinkedHashMap(telemetryStats) }
            recordHistory(
                turn,
                "Turn",
                label,
                "HP ${st["hp"]}/${st["max_hp"]} · SPD ${st["speed"]} WIT ${st["wit"]}",
            )
            return
        }

        if (endpoint.endsWith("/check_event") || endpoint.endsWith("/live_start") || endpoint.endsWith("/minigame_end")) {
            val res = rpc(endpoint, payload)
            mergeCareerState(state, unwrapEnvelope(res))
            updateTelemetry(state)
            when {
                endpoint.endsWith("/check_event") -> {
                    val choiceNum = payload["choice_number"] ?: 0
                    recordHistory(turn, "Choice", "Event ${payload["event_id"]} -> choice $choiceNum", "Brain choice")
                }
                endpoint.endsWith("/live_start") -> {
                    val mastered = lock.withLock { telemetrySongs["mastered"] ?: 0 }
                    recordHistory(turn, "Concert", "Started Grand Live concert", "Songs: $mastered")
                }
                else -> {
                    recordHistory(turn, "Minigame", "Completed minigame", "Turn $turn")
                }
            }
            return
        }

        if (endpoint.endsWith("/race_entry")) {
            val pid = JsonCodec.asInt(payload["program_id"], 0)
            if (pid <= 0) throw BrainApiException("rpc_step race_entry missing program_id")
            executeRaceMacro(
                "race_macro",
                linkedMapOf(
                    "program_id" to pid,
                    "current_turn" to turn,
                    "mandatory" to JsonCodec.asBool(payload["mandatory"], false),
                    "target_rank" to JsonCodec.asInt(payload["target_rank"], 18).let { if (it == 0) 18 else it },
                ),
                state,
            )
            return
        }

        val res = rpc(endpoint, payload)
        mergeCareerState(state, unwrapEnvelope(res))
        updateTelemetry(state)
        recordHistory(turn, "RPC", endpoint, "Turn $turn")
    }

    private fun decideRecovering(brain: BrainClient, state: LinkedHashMap<String, Any?>): Map<String, Any?> {
        var turn = lock.withLock { telemetryTurn }
        var probeResets = 0
        var statResets = 0
        while (true) {
            syncRejectedSquares(state)
            val stripped = StateStripper.stripCareerState(state)
            val delta = linkedMapOf<String, Any?>(
                "drained_stories" to pendingDrainedStories.toList(),
                "settled_races" to pendingSettledRaces.map { LinkedHashMap(it) },
                "last_command" to lastCommand?.let { LinkedHashMap(it) },
                "needs_post_square_reload" to false,
                "rejected_programs" to rejectedPrograms.map { it.toList() },
                "rejected_commands" to rejectedCommands.map { it.toList() },
                "rejected_squares" to rejectedSquares.map { it.toList() },
            )
            val options = linkedMapOf<String, Any?>(
                "burn_clocks" to burnClocks,
                "resume" to resumePending,
            )
            val activeCm = cmOptions
            if (activeCm != null && JsonCodec.asBool(activeCm["cm_mode"], false)) {
                options.putAll(activeCm)
            }
            resumePending = false
            val decision = try {
                brain.decide(viewerIdHash, stripped, delta, options)
            } catch (exc: BrainApiException) {
                val note = when {
                    exc.statusCode == 422 && exc.code == "stat_regression" && statResets < 2 -> {
                        statResets += 1
                        "Stats dropped; brain session reset $statResets/2"
                    }
                    exc.statusCode == 429 && exc.code == "probe_cap" && probeResets < 4 -> {
                        probeResets += 1
                        "probe cap reached; session reset $probeResets/4"
                    }
                    else -> throw exc
                }
                recordHistory(turn, "Recovery", note, "retry")
                closeBrainCareer(brain)
                resumePending = true
                sleepFixed(1.0)
                reloadCareerState(state)
                turn = lock.withLock { telemetryTurn }
                continue
            }
            pendingDrainedStories.clear()
            pendingSettledRaces.clear()
            lastCommand = null
            return decision
        }
    }

    private fun closeBrainCareer(brain: BrainClient) {
        try {
            brain.closeCareer(viewerIdHash)
        } catch (exc: Exception) {
            val turn = lock.withLock { telemetryTurn }
            recordHistory(turn, "Cleanup", "Brain session close failed: ${exc.message}", "close_failed")
        }
    }

    private fun workerEntry(
        umaClient: UmaClient,
        brainClient: BrainClient,
        initialState: Map<String, Any?>?,
        accountData: Map<String, Any?>?,
        maxSteps: Int,
    ) {
        this.client = umaClient
        this.brain = brainClient
        try {
            setViewerHash(umaClient)
            val state = bootstrapOrResumeState(initialState, accountData)
            resumePending = true
            var consecutiveRecoveries = 0

            for (step in 0 until maxSteps) {
                checkStop()
                if (lock.withLock { _finished }) break
                try {
                    drainSingleChoiceEvents(state)
                    checkStop()
                    if (autobuySkillsEnabled() && !_terminalSkillsBought) {
                        buyTerminalSkills(state)
                    }
                    val decision = decideRecovering(brainClient, state)
                    val op = (decision["op"] ?: "").toString()
                    val params = JsonCodec.asMap(decision["params"])
                        ?: throw BrainApiException("bad decision: params missing")

                    when (op) {
                        "rpc_step" -> executeRpcStep(params, state)
                        "race_macro", "race_resume_macro" -> {
                            prevEndpointWasMasterSquare = false
                            executeRaceMacro(op, params, state)
                        }
                        "terminal_skills" -> {
                            if (!autobuySkillsEnabled()) throw BrainApiException("Skill purchases are disabled")
                            var skillArr: List<Any?> = JsonCodec.asList(params["gain_skill_info_array"])
                                ?: JsonCodec.asList(params["skill_select_array"])
                                ?: JsonCodec.asList(params["skill_Select_array"])
                                ?: emptyList()
                            if (skillArr.isEmpty()) {
                                skillArr = terminalSkillBundle(JsonCodec.asMap(state["chara_info"]))
                            }
                            val stepPayload = linkedMapOf<String, Any?>("gain_skill_info_array" to skillArr)
                            if (params["current_turn"] != null) {
                                stepPayload["current_turn"] = params["current_turn"]
                            }
                            executeRpcStep(
                                linkedMapOf("endpoint" to "single_mode_live/gain_skills", "payload" to stepPayload),
                                state,
                            )
                        }
                        "terminal_finish" -> throw BrainApiException("Career ending is disabled")
                        else -> throw BrainApiException("Unsupported brain opcode: $op")
                    }
                    consecutiveRecoveries = 0
                } catch (stop: StopCareerLoop) {
                    throw stop
                } catch (exc: BrainApiException) {
                    if (exc.statusCode == 409) {
                        closeBrainCareer(brainClient)
                        if (exc.code == "career_complete") {
                            val turnNow = lock.withLock {
                                _finished = true
                                _status = "finished"
                                _error = null
                                _result = linkedMapOf("reason" to "career_complete", "turn" to telemetryTurn)
                                lastAction = "FINISHED: career_complete"
                                telemetryTurn
                            }
                            recordHistory(turnNow, "Finish", "career complete", "career_complete")
                            break
                        }
                    }
                    throw exc
                } catch (exc: StateRecoveryException) {
                    consecutiveRecoveries += 1
                    if (consecutiveRecoveries > 4) {
                        throw IllegalStateException("4 consecutive recovery failures: ${exc.message}", exc)
                    }
                    val mode = exc.recovery?.takeIf { it.isNotBlank() } ?: "reconcile"
                    val code = exc.code
                    if (mode == "rebootstrap_and_reconcile" || mode == "replace_identity_and_rebootstrap" || code == 201 || code == 217 || code == 709) {
                        lock.withLock { apiCalls += 1 }
                        umaClient.login(readInfo = false)
                        setViewerHash(umaClient)
                    }
                    reloadCareerState(state, updateTelemetryFlag = false)
                    reconcileRejectedSquare(exc, state)
                    updateTelemetry(state)
                    val turn = JsonCodec.asInt(JsonCodec.asMap(state["chara_info"])?.get("turn"), 0)
                    recordHistory(turn, "Recovery", "State reconciled ($consecutiveRecoveries/4)", mode)
                }
            }
            if (!lock.withLock { _finished }) {
                throw IllegalStateException("Run hit max_steps=$maxSteps")
            }
        } catch (_: StopCareerLoop) {
            lock.withLock {
                _stopped = true
                _status = "stopped"
                lastAction = "STOPPED"
            }
        } catch (exc: Exception) {
            if (stopRequested.get()) {
                lock.withLock {
                    _stopped = true
                    _status = "stopped"
                    lastAction = "STOPPED"
                }
            } else {
                lock.withLock {
                    _error = exc.message ?: exc::class.simpleName ?: "Career error"
                    _status = "error"
                    lastAction = "ERROR: ${exc::class.simpleName ?: "Exception"}"
                }
            }
        } finally {
            runCatching { brainClient.close() }
            lock.withLock {
                _running = false
                if (_status == "running") {
                    _status = if (_finished) "finished" else "idle"
                }
            }
            onRunningChanged?.invoke(false)
        }
    }

    companion object {
        private const val AUTOBUY_SKILLS_ENV = "SWEEPY_AUTOBUY_SKILLS"
        private const val AUTOBUY_SKILLS_FLAG = "autobuy_skills"
        private val ON_VALUES = setOf("1", "true", "on", "yes", "enabled")
        private val COMMON_WRAPPERS = listOf("single_mode_start_common", "single_mode_load_common")
        private val ENVELOPE_DATA_MARKERS = setOf(
            "chara_info",
            "single_mode_start_common",
            "single_mode_load_common",
            "single_mode_factor_select_common",
            "single_mode_finish_common",
            "race_start_info",
            "race_reward_info",
            "live_data_set",
            "tp_info",
            "friend_support_card_data",
            "summary_user_info_array",
            "user_info",
        )
        private val LIFT_KEYS = listOf(
            "chara_info",
            "home_info",
            "unchecked_event_array",
            "race_condition_array",
            "race_random_program_array",
            "race_start_info",
            "race_history",
            "single_mode_finish_common",
        )
        private val MERGE_DICT_KEYS = listOf(
            "chara_info",
            "home_info",
            "live_data_set",
            "race_reward_info",
            "command_result",
            "single_mode_finish_common",
        )

        private val COMMAND_LABELS = mapOf(
            101 to "Speed Training",
            102 to "Power Training",
            103 to "Guts Training",
            105 to "Stamina Training",
            106 to "Wit Training",
            301 to "Outing",
            302 to "Outing",
            303 to "Outing",
            304 to "Summer Outing",
            390 to "Pal Outing",
            401 to "Race",
            601 to "Summer Speed",
            602 to "Summer Stamina",
            603 to "Summer Power",
            604 to "Summer Guts",
            605 to "Summer Wit",
            701 to "Rest",
            801 to "Infirmary",
        )

        private fun defaultStats(): LinkedHashMap<String, Int> = linkedMapOf(
            "hp" to 100,
            "max_hp" to 100,
            "mood" to 3,
            "speed" to 0,
            "stamina" to 0,
            "power" to 0,
            "guts" to 0,
            "wit" to 0,
            "sp" to 0,
            "fans" to 0,
        )

        private fun defaultTokens(): LinkedHashMap<String, Int> = linkedMapOf(
            "da" to 0, "pa" to 0, "vo" to 0, "vi" to 0, "me" to 0,
        )

        private fun defaultSongs(): LinkedHashMap<String, Int> = linkedMapOf(
            "mastered" to 0, "staged" to 0, "concerts_done" to 0,
        )

        private fun trimPairList(list: MutableList<List<Int>>, maxSize: Int) {
            if (list.size > maxSize) {
                val keep = list.subList(list.size - maxSize, list.size).toList()
                list.clear()
                list.addAll(keep)
            }
        }

        private fun strictPositiveInt(v: Any?): Int? {
            if (v == null || v is Boolean) return null
            val n = when (v) {
                is Number -> v.toLong()
                else -> return null
            }
            return if (n > 0L && n <= Int.MAX_VALUE) n.toInt() else null
        }

        private fun nonNegativeIntOrZero(v: Any?): Int {
            if (v == null || v is Boolean) return 0
            return when (v) {
                is Number -> v.toInt()
                is String -> v.trim().toIntOrNull() ?: 0
                else -> 0
            }
        }

        private fun nonNegativeIntOrNull(v: Any?): Int? {
            if (v == null || v is Boolean) return null
            return when (v) {
                is Number -> v.toInt()
                is String -> v.trim().toIntOrNull()
                else -> null
            }
        }

        fun unwrapEnvelope(resp: Map<String, Any?>): LinkedHashMap<String, Any?> {
            val inner = JsonCodec.asMap(resp["data"])
            if (inner != null && ENVELOPE_DATA_MARKERS.any { it in inner }) {
                return LinkedHashMap(inner)
            }
            return LinkedHashMap(resp)
        }

        fun normalizeCareerState(raw: Map<String, Any?>): LinkedHashMap<String, Any?> {
            val state = LinkedHashMap(raw)
            for (wrapperKey in COMMON_WRAPPERS) {
                val common = JsonCodec.asMap(state[wrapperKey]) ?: continue
                for (liftKey in LIFT_KEYS) {
                    if (state[liftKey] == null && common.containsKey(liftKey)) {
                        state[liftKey] = common[liftKey]
                    }
                }
            }
            if (state["unchecked_event_array"] == null) {
                state["unchecked_event_array"] = emptyList<Any?>()
            }
            if (state["race_condition_array"] == null) {
                state["race_condition_array"] = emptyList<Any?>()
            }
            return state
        }

        fun mergeCareerState(
            state: LinkedHashMap<String, Any?>,
            updateRaw: Map<String, Any?>,
            clearRace: Boolean = false,
        ) {
            val update = normalizeCareerState(updateRaw)
            val hasWrapper = COMMON_WRAPPERS.any { JsonCodec.asMap(updateRaw[it]) != null }
            for (key in MERGE_DICT_KEYS) {
                val valMap = JsonCodec.asMap(update[key]) ?: continue
                if (key == "live_data_set") {
                    val existing = JsonCodec.asMap(state[key])
                    if (existing != null) {
                        val merged = LinkedHashMap(existing)
                        merged.putAll(valMap)
                        state[key] = merged
                        continue
                    }
                }
                state[key] = LinkedHashMap(valMap)
            }
            if ("unchecked_event_array" in updateRaw || hasWrapper) {
                JsonCodec.asList(update["unchecked_event_array"])?.let { state["unchecked_event_array"] = it }
            }
            if ("race_condition_array" in updateRaw || hasWrapper) {
                JsonCodec.asList(update["race_condition_array"])?.let { state["race_condition_array"] = it }
            }
            if ("race_history" in updateRaw || hasWrapper) {
                JsonCodec.asList(update["race_history"])?.let { state["race_history"] = it }
            }
            if (clearRace) {
                state["race_start_info"] = null
                state["race_scenario"] = null
            } else {
                val rsi = update["race_start_info"]
                if (("race_start_info" in updateRaw || hasWrapper) && rsi != null) {
                    state["race_start_info"] = rsi
                }
                if ("race_scenario" in updateRaw && updateRaw["race_scenario"] != null) {
                    state["race_scenario"] = updateRaw["race_scenario"]
                }
            }
        }

        fun eventChoices(event: Map<String, Any?>): List<Any?> {
            val contents = JsonCodec.asMap(event["event_contents_info"])
            if (contents != null) {
                val choices = JsonCodec.asList(contents["choice_array"])
                if (!choices.isNullOrEmpty()) return choices
            }
            return JsonCodec.asList(event["choice_array"]) ?: emptyList()
        }
    }
}
