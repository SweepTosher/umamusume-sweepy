package top.mayano.sweepy.core

object StateStripper {
    val ALLOWED_TOP_KEYS: Set<String> = setOf(
        "chara_info",
        "home_info",
        "live_data_set",
        "race_start_info",
        "race_condition_array",
        "race_history",
        "unchecked_event_array",
        "single_mode_finish_common",
        "race_reward_info",
        "command_result",
    )

    private val PRIVATE_KEY_MARKERS = listOf(
        "viewerid", "steamid", "authkey", "sessionticket", "deviceid", "udid"
    )
    private val PRIVATE_EXACT_KEYS = setOf(
        "friendcode", "trainername", "ownername", "ownertrainername"
    )
    private val LIFT_START_KEYS = listOf(
        "chara_info",
        "home_info",
        "unchecked_event_array",
        "race_condition_array",
        "race_start_info",
        "race_history",
        "single_mode_finish_common",
    )
    private val IGNORED_LIVE_DATA_KEYS = setOf(
        "evaluation_info_array", "not_up_parameter_info", "not_down_parameter_info"
    )

    private fun normKey(value: Any?): String = buildString {
        for (ch in (value?.toString() ?: "").lowercase()) {
            if (ch.isLetterOrDigit()) append(ch)
        }
    }

    fun scrubPrivate(value: Any?): Any? = when (value) {
        is Map<*, *> -> {
            val cleaned = LinkedHashMap<String, Any?>()
            for ((k, item) in value) {
                if (k == null) continue
                val keyStr = k.toString()
                val norm = normKey(keyStr)
                if (norm in PRIVATE_EXACT_KEYS) continue
                if (PRIVATE_KEY_MARKERS.any { it in norm }) continue
                cleaned[keyStr] = scrubPrivate(item)
            }
            cleaned
        }
        is List<*> -> value.map { scrubPrivate(it) }
        else -> value
    }

    fun unwrapData(raw: Any?): MutableMap<String, Any?> {
        val m = JsonCodec.asMutableMap(raw) ?: return linkedMapOf()
        val inner = JsonCodec.asMutableMap(m["data"])
        return inner ?: m
    }

    fun stripCareerState(rawData: Map<String, Any?>): LinkedHashMap<String, Any?> {
        val innerData = JsonCodec.asMutableMap(rawData["data"])
        val source: MutableMap<String, Any?> = if (
            innerData != null &&
            "chara_info" !in rawData &&
            "single_mode_start_common" !in rawData &&
            "live_data_set" !in rawData
        ) {
            LinkedHashMap(innerData)
        } else {
            LinkedHashMap(rawData)
        }

        for (wrapperKey in listOf("single_mode_start_common", "single_mode_load_common")) {
            val common = JsonCodec.asMap(source[wrapperKey]) ?: continue
            for (k in LIFT_START_KEYS) {
                if (source[k] == null && common.containsKey(k)) {
                    source[k] = common[k]
                }
            }
        }

        val out = LinkedHashMap<String, Any?>()
        for ((key, value) in source) {
            if (key !in ALLOWED_TOP_KEYS) continue
            when (key) {
                "live_data_set" -> {
                    val lds = JsonCodec.asMap(value)
                    if (lds != null) {
                        val copy = LinkedHashMap<String, Any?>()
                        for ((lk, lv) in lds) {
                            if (lk !in IGNORED_LIVE_DATA_KEYS) {
                                copy[lk] = lv
                            }
                        }
                        out["live_data_set"] = copy
                    } else {
                        out["live_data_set"] = value
                    }
                }
                "race_start_info" -> {
                    val rsi = JsonCodec.asMap(value)
                    out["race_start_info"] = if (rsi != null) {
                        val pid = rsi["program_id"]
                        if (pid != null) linkedMapOf("program_id" to pid) else linkedMapOf<String, Any?>()
                    } else {
                        null
                    }
                }
                "race_condition_array" -> {
                    val list = JsonCodec.asList(value)
                    val compacted = mutableListOf<LinkedHashMap<String, Any?>>()
                    if (list != null) {
                        for (item in list) {
                            val row = JsonCodec.asMap(item) ?: continue
                            val pid = JsonCodec.asLongOrNull(row["program_id"]) ?: continue
                            compacted.add(linkedMapOf("program_id" to pid.toInt()))
                        }
                    }
                    out["race_condition_array"] = compacted
                }
                else -> out[key] = value
            }
        }
        @Suppress("UNCHECKED_CAST")
        return scrubPrivate(out) as LinkedHashMap<String, Any?>
    }

    private val CM_MATE_INT_FIELDS = listOf(
        "card_id",
        "speed",
        "stamina",
        "power",
        "guts",
        "wiz",
        "running_style",
        "proper_distance_short",
        "proper_distance_mile",
        "proper_distance_middle",
        "proper_distance_long",
        "proper_ground_turf",
        "proper_ground_dirt",
        "proper_running_style_nige",
        "proper_running_style_senko",
        "proper_running_style_sashi",
        "proper_running_style_oikomi",
    )

    fun trainedCharaIndex(rawAccountData: Map<String, Any?>?): Map<Long, Map<String, Any?>> {
        val data = unwrapData(rawAccountData)
        val byTid = LinkedHashMap<Long, Map<String, Any?>>()
        for (item in JsonCodec.asList(data["trained_chara_array"]) ?: emptyList()) {
            val tc = JsonCodec.asMap(item) ?: continue
            val tid = JsonCodec.asLongOrNull(tc["trained_chara_id"]) ?: continue
            byTid[tid] = tc
        }
        return byTid
    }

    fun stripCmMate(
        rawMate: Map<String, Any?>,
        roleOverride: String? = null,
        styleOverride: Int? = null,
    ): LinkedHashMap<String, Any?> {
        val cleaned = LinkedHashMap<String, Any?>()
        for (field in CM_MATE_INT_FIELDS) {
            val v = JsonCodec.asLongOrNull(rawMate[field])
            if (v != null) cleaned[field] = v.toInt()
        }
        if ("power" !in cleaned && rawMate["pow"] != null) {
            cleaned["power"] = JsonCodec.asInt(rawMate["pow"])
        }
        if ("wiz" !in cleaned && rawMate["wisdom"] != null) {
            cleaned["wiz"] = JsonCodec.asInt(rawMate["wisdom"])
        }
        val stats = JsonCodec.asList(rawMate["stats"])
        if (stats != null && stats.size >= 5) {
            cleaned["stats"] = stats.take(5).map { JsonCodec.asInt(it) }
        }
        if (styleOverride != null && styleOverride in 1..5) {
            cleaned["running_style"] = styleOverride
        } else if ("running_style" !in cleaned) {
            val alt = JsonCodec.asLongOrNull(rawMate["racingStyle"] ?: rawMate["style"])?.toInt()
            if (alt != null) {
                cleaned["running_style"] = if (alt in 1..5) alt else 2
            }
        }
        val apts = JsonCodec.asList(rawMate["aptitudes"])
        if (apts != null) {
            cleaned["aptitudes"] = apts.take(3).map { it?.toString() ?: "" }
        }
        val rawSkills = JsonCodec.asList(rawMate["skills"] ?: rawMate["skill_array"]) ?: emptyList()
        val skillArray = mutableListOf<Map<String, Int>>()
        for (item in rawSkills.take(64)) {
            when (item) {
                is Map<*, *> -> JsonCodec.asLongOrNull(item["skill_id"])?.let {
                    skillArray.add(mapOf("skill_id" to it.toInt()))
                }
                is List<*> -> if (item.isNotEmpty()) {
                    JsonCodec.asLongOrNull(item[0])?.let { skillArray.add(mapOf("skill_id" to it.toInt())) }
                }
                else -> JsonCodec.asLongOrNull(item)?.let { skillArray.add(mapOf("skill_id" to it.toInt())) }
            }
        }
        cleaned["skill_array"] = skillArray

        val roleStr = (roleOverride ?: rawMate["role"]?.toString() ?: "").trim().lowercase()
        if (roleStr.isNotEmpty() && roleStr != "auto") {
            cleaned["role"] = roleStr
            if ("deb" in roleStr) cleaned["is_debuffer"] = true
            else if ("block" in roleStr) cleaned["is_blocker"] = true
        } else {
            if (JsonCodec.asBool(rawMate["is_debuffer"], false) ||
                (JsonCodec.asInt(rawMate["style"], -1) == 6 && "racingStyle" in rawMate)
            ) {
                cleaned["is_debuffer"] = true
            }
            if (JsonCodec.asBool(rawMate["is_blocker"], false)) {
                cleaned["is_blocker"] = true
            }
        }
        @Suppress("UNCHECKED_CAST")
        return scrubPrivate(cleaned) as LinkedHashMap<String, Any?>
    }

    fun resolveCmOptionsForAccount(
        cmCfg: Map<String, Any?>?,
        rawAccountData: Map<String, Any?>? = null,
    ): LinkedHashMap<String, Any?>? {
        if (cmCfg == null || !JsonCodec.asBool(cmCfg["cm_mode"], false)) return null
        val byTid = trainedCharaIndex(rawAccountData)
        val resolvedMates = mutableListOf<Map<String, Any?>>()
        val mateRoles = JsonCodec.asList(cmCfg["mate_roles"]) ?: emptyList()
        val rawExplicit = JsonCodec.asList(cmCfg["cm_mates"])
        if (rawExplicit != null) {
            if (rawExplicit.size > 2) {
                throw IllegalArgumentException("Expected at most 2 teammates, got ${rawExplicit.size}")
            }
            rawExplicit.forEachIndexed { idx, item ->
                val m = JsonCodec.asMap(item) ?: return@forEachIndexed
                val rOv = mateRoles.getOrNull(idx)?.toString()?.takeIf { it.isNotEmpty() }
                resolvedMates.add(stripCmMate(m, roleOverride = rOv))
            }
        } else {
            val mateIds = JsonCodec.asList(cmCfg["mate_ids"]) ?: emptyList()
            val mateSnaps = JsonCodec.asList(cmCfg["mate_snapshots"]) ?: emptyList()
            val count = minOf(2, maxOf(mateIds.size, mateSnaps.size))
            for (idx in 0 until count) {
                val tid = JsonCodec.asLongOrNull(mateIds.getOrNull(idx)) ?: continue
                val rOv = mateRoles.getOrNull(idx)?.toString()?.takeIf { it.isNotEmpty() }
                val snap = JsonCodec.asMap(mateSnaps.getOrNull(idx))
                val found = byTid[tid]
                if (found != null) {
                    resolvedMates.add(stripCmMate(found, roleOverride = rOv))
                } else if (snap != null && JsonCodec.asLongOrNull(snap["_snap_tid"]) == tid) {
                    resolvedMates.add(stripCmMate(snap, roleOverride = rOv))
                } else {
                    throw IllegalArgumentException("Selected teammate veteran $tid not found in account veterans")
                }
            }
        }

        val cmRole = normalizeCmRole(cmCfg["cm_role"] ?: 0, cmCfg["cm_target"])
        val cmStyle = normalizeCmStyle(cmCfg["cm_style"] ?: 0)
        val envKeys = listOf("track", "distance", "ground", "surface", "ground_condition", "weather", "season", "course_id", "inout")
        val rawCourse = cmCfg["cm_course"]
        val hasEnvFields = rawCourse is Map<*, *> || envKeys.any { cmCfg[it] != null }
        val cmCourseOut: Any = if (hasEnvFields) {
            val cp: LinkedHashMap<String, Any?> = when (rawCourse) {
                is Map<*, *> -> JsonCodec.asMutableMap(rawCourse) as? LinkedHashMap<String, Any?> ?: linkedMapOf()
                is String -> if (rawCourse.isNotBlank()) linkedMapOf("slug" to rawCourse.trim()) else linkedMapOf()
                else -> linkedMapOf()
            }
            if ("surface" in cp && "ground" !in cp) {
                cp["ground"] = cp.remove("surface")
            }
            cmCfg["course_id"]?.let { cp["course_id"] = JsonCodec.asInt(it) }
            for (k in listOf("track", "inout", "ground_condition", "weather", "season")) {
                cmCfg[k]?.let { cp[k] = it }
            }
            cmCfg["distance"]?.let { cp["distance"] = JsonCodec.asInt(it) }
            when {
                cmCfg["ground"] != null -> cp["ground"] = cmCfg["ground"]
                cmCfg["surface"] != null -> cp["ground"] = cmCfg["surface"]
            }
            scrubPrivate(cp)!!
        } else {
            rawCourse ?: "sagittarius"
        }
        return linkedMapOf(
            "cm_mode" to true,
            "cm_course" to cmCourseOut,
            "cm_role" to cmRole,
            "cm_style" to cmStyle,
            "cm_mates" to resolvedMates,
        )
    }
}
