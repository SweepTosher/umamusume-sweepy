package top.mayano.sweepy.core

import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

interface AssetSource {
    fun readBytes(relativePath: String): ByteArray?
    fun readText(relativePath: String): String? = readBytes(relativePath)?.toString(Charsets.UTF_8)
}

object UmaDumpExport {
    const val FINAL_CAREER_TURN = 78

    private val REQUIRED_NUMBER_FIELDS = listOf(
        "card_id", "speed", "stamina", "power", "guts", "wiz", "motivation", "skill_point",
        "race_running_style", "proper_distance_short", "proper_distance_mile",
        "proper_distance_middle", "proper_distance_long", "proper_running_style_nige",
        "proper_running_style_senko", "proper_running_style_sashi", "proper_running_style_oikomi",
        "proper_ground_turf", "proper_ground_dirt",
    )
    private val OPTIONAL_NUMBER_FIELDS = listOf("fans", "talent_level", "turn", "single_mode_chara_id", "scenario_id")
    private val SKILL_FIELDS = listOf("skill_id", "level")
    private val HINT_FIELDS = listOf("group_id", "rarity", "level")
    private val UNSAFE_RE = Regex("[<>:\"/\\\\|?*\\x00-\\x1F]")
    private val SPACE_RE = Regex("\\s+")
    private val TS_FMT = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")

    fun isFinalTurn(chara: Map<String, Any?>?): Boolean {
        val turn = JsonCodec.asLongOrNull(chara?.get("turn")) ?: return false
        return turn >= FINAL_CAREER_TURN
    }

    private fun extractRows(values: Any?, fields: List<String>): List<LinkedHashMap<String, Long>>? {
        val list = JsonCodec.asList(values) ?: return null
        val rows = mutableListOf<LinkedHashMap<String, Long>>()
        for (item in list) {
            val m = JsonCodec.asMap(item) ?: return null
            val row = LinkedHashMap<String, Long>()
            for (f in fields) {
                val num = JsonCodec.asLongOrNull(m[f]) ?: return null
                row[f] = num
            }
            rows.add(row)
        }
        return rows
    }

    fun buildFinalTurnPayload(state: Map<String, Any?>?): LinkedHashMap<String, Any?>? {
        if (state == null) return null
        val chara = JsonCodec.asMap(state["chara_info"]) ?: return null
        val info = LinkedHashMap<String, Any?>()
        for (f in REQUIRED_NUMBER_FIELDS) {
            val num = JsonCodec.asLongOrNull(chara[f]) ?: return null
            info[f] = num
        }
        val skills = extractRows(chara["skill_array"], SKILL_FIELDS) ?: return null
        info["skill_array"] = skills
        val tips = extractRows(chara["skill_tips_array"] ?: emptyList<Any?>(), HINT_FIELDS) ?: return null
        info["skill_tips_array"] = tips
        for (f in OPTIONAL_NUMBER_FIELDS) {
            JsonCodec.asLongOrNull(chara[f])?.let { info[f] = it }
        }
        return linkedMapOf("chara_info" to info)
    }

    fun exportFilename(
        chara: Map<String, Any?>?,
        name: String? = null,
        moment: LocalDateTime = LocalDateTime.now(),
    ): String {
        val label = name ?: chara?.get("name")?.toString()
        val cardId = JsonCodec.asLongOrNull(chara?.get("card_id"))
        val fallback = if (cardId != null) "card_$cardId" else "umadump"
        val cleaned = SPACE_RE.replace(UNSAFE_RE.replace(label ?: "", "").trim(), "_")
            .trim('.', '_')
            .take(80)
            .ifEmpty { fallback }
        return "${cleaned}_${moment.format(TS_FMT)}.json"
    }
}

class Catalog(assets: AssetSource) {
    val charaNames: Map<String, String>
    val cmPresets: List<Map<String, Any?>>
    val cmCourses: List<Map<String, Any?>>
    val skillShop: SkillShop?

    init {
        val namesRaw = assets.readText("data/chara_names.json")?.let {
            runCatching { JsonCodec.decodeMap(it) }.getOrNull()
        } ?: emptyMap()
        charaNames = namesRaw.entries.associate { it.key to (it.value?.toString() ?: "") }

        val cmRaw = assets.readText("data/cm_courses.json")?.let {
            runCatching { JsonCodec.decodeMap(it) }.getOrNull()
        } ?: emptyMap()
        val presetsList = (JsonCodec.asList(cmRaw["presets"]) ?: emptyList())
            .mapNotNull { JsonCodec.asMap(it) }
        cmPresets = presetsList.ifEmpty { DEFAULT_PRESETS }
        val coursesList = (JsonCodec.asList(cmRaw["courses"]) ?: emptyList())
            .mapNotNull { JsonCodec.asMap(it) }
        cmCourses = coursesList.ifEmpty { cmPresets }

        skillShop = assets.readText("skill_catalog.json")?.let { txt ->
            runCatching { SkillShop(JsonCodec.decodeMap(txt)) }.getOrNull()
        }
    }

    fun charaName(cardId: Any?): String {
        val cid = cardId?.toString() ?: ""
        return charaNames[cid] ?: "Unknown ($cid)"
    }

    fun cmMetadata(): LinkedHashMap<String, Any?> {
        val tracks = cmCourses.mapNotNull { it["track"]?.toString()?.takeIf(String::isNotBlank) }.distinct().sorted()
        return linkedMapOf(
            "presets" to cmPresets,
            "courses" to cmCourses,
            "tracks" to tracks,
            "ground_conditions" to listOf(
                mapOf("id" to 1, "label" to "Firm"),
                mapOf("id" to 2, "label" to "Good"),
                mapOf("id" to 3, "label" to "Soft"),
                mapOf("id" to 4, "label" to "Heavy"),
            ),
            "weathers" to listOf(
                mapOf("id" to 1, "label" to "Sunny"),
                mapOf("id" to 2, "label" to "Cloudy"),
                mapOf("id" to 3, "label" to "Rainy"),
                mapOf("id" to 4, "label" to "Snowy"),
            ),
            "seasons" to listOf(
                mapOf("id" to 1, "label" to "Spring"),
                mapOf("id" to 2, "label" to "Summer"),
                mapOf("id" to 3, "label" to "Autumn"),
                mapOf("id" to 4, "label" to "Winter"),
            ),
            "styles" to listOf(
                mapOf("id" to 0, "label" to "Auto"),
                mapOf("id" to 1, "label" to "Front"),
                mapOf("id" to 2, "label" to "Pace"),
                mapOf("id" to 3, "label" to "Late"),
                mapOf("id" to 4, "label" to "End"),
                mapOf("id" to 5, "label" to "Runaway"),
            ),
            "modes" to listOf(
                mapOf("id" to 0, "slug" to "solo", "label" to "Solo", "mates_required" to 0, "mates_max" to 0),
                mapOf("id" to 1, "slug" to "ace", "label" to "Ace", "mates_required" to 0, "mates_max" to 2),
                mapOf("id" to 2, "slug" to "support", "label" to "Support (Debuffer)", "mates_required" to 2, "mates_max" to 2),
                mapOf("id" to 3, "slug" to "blocker", "label" to "Support (Blocker)", "mates_required" to 2, "mates_max" to 2),
            ),
            "ace_targets" to listOf(
                mapOf("id" to "carry", "label" to "Carry"),
                mapOf("id" to "debuffer", "label" to "Debuffer"),
            ),
            "support_subroles" to listOf(
                mapOf("id" to 2, "label" to "Debuffer"),
                mapOf("id" to 3, "label" to "Blocker"),
            ),
        )
    }

    fun formatAccountStatus(rawData: Map<String, Any?>, careerData: Map<String, Any?>? = null): LinkedHashMap<String, Any?> {
        val data = StateStripper.unwrapData(rawData)
        val userInfo = JsonCodec.asMap(data["user_info"]) ?: emptyMap()
        val tpInfo = JsonCodec.asMap(data["tp_info"]) ?: emptyMap()
        val items = data["item_list"] ?: data["user_item_array"]
        var careerSrc = JsonCodec.asMap(data["single_mode_chara_light"] ?: data["single_mode_chara"])
        if (careerData != null) {
            val inner = StateStripper.unwrapData(careerData)
            JsonCodec.asMap(inner["chara_info"])?.let { careerSrc = it }
        }
        val careerOut: LinkedHashMap<String, Any?>? = if (
            careerSrc != null &&
            maxOf(
                JsonCodec.asLong(careerSrc["card_id"], 0L),
                JsonCodec.asLong(careerSrc["single_mode_chara_id"], 0L)
            ) > 0L
        ) {
            val cid = (careerSrc["card_id"] ?: "").toString()
            linkedMapOf(
                "active" to true,
                "single_mode_chara_id" to JsonCodec.asLong(careerSrc["single_mode_chara_id"], 0L),
                "card_id" to cid,
                "name" to charaName(cid),
                "turn" to JsonCodec.asInt(careerSrc["turn"], 0),
                "scenario_id" to JsonCodec.asInt(careerSrc["scenario_id"], 0),
            )
        } else {
            null
        }
        return linkedMapOf(
            "trainer_name" to (userInfo["name"]?.toString() ?: ""),
            "tp" to linkedMapOf(
                "current" to JsonCodec.asInt(tpInfo["current_tp"], 0),
                "max" to JsonCodec.asInt(tpInfo["max_tp"], 100),
            ),
            "clocks" to itemCount(items, 95),
            "career" to careerOut,
        )
    }

    fun formatVeterans(rawData: Map<String, Any?>?): List<LinkedHashMap<String, Any?>> {
        if (rawData == null) return emptyList()
        val data = StateStripper.unwrapData(rawData)
        val rawVets = JsonCodec.asList(data["trained_chara_array"]) ?: return emptyList()
        val out = mutableListOf<LinkedHashMap<String, Any?>>()
        for (item in rawVets) {
            val tc = JsonCodec.asMap(item) ?: continue
            val tid = JsonCodec.asLong(tc["trained_chara_id"], 0L)
            if (tid <= 0L) continue
            val cid = JsonCodec.asInt(tc["card_id"], 0)
            out.add(
                linkedMapOf(
                    "trained_chara_id" to tid,
                    "card_id" to cid,
                    "name" to charaName(cid),
                    "rank_score" to JsonCodec.asInt(tc["rank_score"], 0),
                    "stats" to listOf(
                        JsonCodec.asInt(tc["speed"], 0),
                        JsonCodec.asInt(tc["stamina"], 0),
                        JsonCodec.asInt(tc["power"], 0),
                        JsonCodec.asInt(tc["guts"], 0),
                        JsonCodec.asInt(tc["wiz"], 0),
                    ),
                    "running_style" to JsonCodec.asInt(tc["running_style"], 2),
                    "proper_distance" to listOf(
                        JsonCodec.asInt(tc["proper_distance_short"], 1),
                        JsonCodec.asInt(tc["proper_distance_mile"], 1),
                        JsonCodec.asInt(tc["proper_distance_middle"], 1),
                        JsonCodec.asInt(tc["proper_distance_long"], 1),
                    ),
                    "proper_ground" to listOf(
                        JsonCodec.asInt(tc["proper_ground_turf"], 1),
                        JsonCodec.asInt(tc["proper_ground_dirt"], 1),
                    ),
                    "skill_count" to (JsonCodec.asList(tc["skill_array"])?.size ?: 0),
                )
            )
        }
        out.sortWith(
            compareByDescending<LinkedHashMap<String, Any?>> { JsonCodec.asInt(it["rank_score"]) }
                .thenByDescending { JsonCodec.asLong(it["trained_chara_id"]) }
        )
        return out
    }

    companion object {
        fun itemCount(items: Any?, itemId: Int): Int {
            val list = JsonCodec.asList(items) ?: return 0
            for (item in list) {
                val row = JsonCodec.asMap(item) ?: continue
                if (JsonCodec.asInt(row["item_id"], -1) == itemId) {
                    return JsonCodec.asInt(row["number"], 0)
                }
            }
            return 0
        }

        private val DEFAULT_PRESETS: List<Map<String, Any?>> = listOf(
            mapOf("slug" to "sagittarius", "name" to "Sagittarius (Nakayama 2500m Turf)", "course_id" to 10506, "track" to "Nakayama", "distance" to 2500, "ground" to 1, "distance_type" to 4, "turn" to 1, "inout" to 1, "ground_condition" to 1, "weather" to 1, "season" to 4),
        )
    }
}
