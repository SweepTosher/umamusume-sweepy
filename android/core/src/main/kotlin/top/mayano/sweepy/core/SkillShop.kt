package top.mayano.sweepy.core

class SkillShop(payload: Map<String, Any?>) {
    private data class Branch(val distance: Int, val style: Int)

    private data class SkillEntry(
        val skillId: Int,
        val rarity: Int,
        val groupId: Int,
        val groupRate: Int,
        val gradeValue: Int,
        val baseCost: Int,
        val branches: List<Branch>,
    )

    val skills: MutableMap<Int, Map<String, Any?>> = LinkedHashMap()
    private val typedSkills = HashMap<Int, SkillEntry>()
    private val groups = LinkedHashMap<Int, MutableList<SkillEntry>>()
    val innate: MutableMap<Int, MutableSet<Int>> = HashMap()
    val awakening: MutableMap<Int, MutableList<Pair<Int, Int>>> = HashMap()

    init {
        val rawInnate = JsonCodec.asMap(payload["innate"]) ?: emptyMap()
        for ((k, v) in rawInnate) {
            val cid = k.toIntOrNull() ?: continue
            val sids = (JsonCodec.asList(v) ?: emptyList()).mapNotNull { JsonCodec.asLongOrNull(it)?.toInt() }.toMutableSet()
            innate[cid] = sids
        }
        val rawAwakening = JsonCodec.asMap(payload["awakening"]) ?: emptyMap()
        for ((k, v) in rawAwakening) {
            val cid = k.toIntOrNull() ?: continue
            val pairs = mutableListOf<Pair<Int, Int>>()
            for (item in JsonCodec.asList(v) ?: emptyList()) {
                val p = JsonCodec.asList(item) ?: continue
                if (p.size >= 2) {
                    pairs.add(JsonCodec.asInt(p[0]) to JsonCodec.asInt(p[1]))
                }
            }
            awakening[cid] = pairs
        }
        val rows = JsonCodec.asList(payload["skills"]) ?: emptyList()
        for (item in rows) {
            val row = JsonCodec.asList(item) ?: continue
            if (row.size < 8) continue
            val skillId = JsonCodec.asInt(row[0])
            val rarity = JsonCodec.asInt(row[1])
            val groupId = JsonCodec.asInt(row[2])
            val groupRate = JsonCodec.asInt(row[3])
            val gradeValue = JsonCodec.asInt(row[4])
            val baseCost = JsonCodec.asInt(row[5])
            val branches = parseBranches(row[6], row[7])
            val entry = SkillEntry(skillId, rarity, groupId, groupRate, gradeValue, baseCost, branches)
            typedSkills[skillId] = entry
            skills[skillId] = mapOf(
                "skill_id" to skillId,
                "rarity" to rarity,
                "group_id" to groupId,
                "group_rate" to groupRate,
                "grade_value" to gradeValue,
                "base_cost" to baseCost,
            )
            if (gradeValue > 0 && groupRate >= 1) {
                groups.getOrPut(groupId) { mutableListOf() }.add(entry)
            }
        }
        for (entries in groups.values) {
            entries.sortBy { it.groupRate }
        }
    }

    private fun parseBranches(cond1: Any?, cond2: Any?): List<Branch> {
        val branches = mutableListOf<Branch>()
        for (cond in listOf(cond1?.toString() ?: "", cond2?.toString() ?: "")) {
            if (cond.isEmpty()) continue
            var unconditional = false
            for (chunk in cond.split('@')) {
                var distance = 0
                var style = 0
                var hasPredicate = false
                for (token in chunk.split('&')) {
                    val m = BRANCH_TOKEN.matchEntire(token.trim()) ?: continue
                    hasPredicate = true
                    val kind = m.groupValues[1]
                    val v = m.groupValues[2].toInt()
                    if (kind == "distance_type" && distance == 0) distance = v
                    else if (kind == "running_style" && style == 0) style = v
                }
                if (!hasPredicate) {
                    unconditional = true
                    break
                }
                branches.add(Branch(distance, style))
            }
            if (unconditional) return emptyList()
        }
        return branches
    }

    private fun aptNd(rank: Int): Pair<Int, Int> {
        val value = rank.coerceIn(1, 8)
        return when {
            value == 1 -> 7 to 10
            value <= 4 -> 8 to 10
            value <= 6 -> 9 to 10
            else -> 11 to 10
        }
    }

    private fun aptitudes(chara: Map<String, Any?>): IntArray = IntArray(APTITUDE_DEFAULTS.size) { i ->
        val (key, def) = APTITUDE_DEFAULTS[i]
        JsonCodec.asLongOrNull(chara[key])?.toInt() ?: def
    }

    private fun score(entry: SkillEntry, apts: IntArray): Int {
        val grade = entry.gradeValue
        if (entry.branches.isEmpty()) return grade
        var bestN = 0
        var bestD = 1
        for (b in entry.branches) {
            var n = 1
            var d = 1
            if (b.distance in 1..4) {
                val (fn, fd) = aptNd(apts[1 + b.distance])
                n *= fn
                d *= fd
            }
            if (b.style in 1..4) {
                val (fn, fd) = aptNd(apts[5 + b.style])
                n *= fn
                d *= fd
            }
            if (bestN == 0 || n * bestD > bestN * d) {
                bestN = n
                bestD = d
            }
        }
        return if (grade >= 0) {
            (2 * grade * bestN + bestD) / (2 * bestD)
        } else {
            -((2 * (-grade) * bestN + bestD) / (2 * bestD))
        }
    }

    private fun hints(chara: Map<String, Any?>): Pair<Map<Pair<Int, Int>, Int>, Map<Int, Int>> {
        val byGroup = HashMap<Pair<Int, Int>, Int>()
        val bySkill = HashMap<Int, Int>()
        for (item in JsonCodec.asList(chara["skill_tips_array"]) ?: emptyList()) {
            val tip = JsonCodec.asMap(item) ?: continue
            val level = JsonCodec.asInt(tip["level"] ?: tip["skill_level"] ?: tip["tips_level"], 0)
            if (tip.containsKey("group_id") && tip.containsKey("rarity")) {
                val key = JsonCodec.asInt(tip["group_id"]) to JsonCodec.asInt(tip["rarity"])
                byGroup[key] = maxOf(byGroup[key] ?: 0, level)
            } else if (tip.containsKey("group_id")) {
                val key = JsonCodec.asInt(tip["group_id"]) to 1
                byGroup[key] = maxOf(byGroup[key] ?: 0, level)
            }
            if (tip.containsKey("skill_id")) {
                val sid = JsonCodec.asInt(tip["skill_id"])
                bySkill[sid] = maxOf(bySkill[sid] ?: 0, level)
            }
        }
        return byGroup to bySkill
    }

    private fun unlockedCardSkills(chara: Map<String, Any?>): Set<Int> {
        val cardId = JsonCodec.asInt(chara["card_id"], 0)
        val talentLevel = JsonCodec.asInt(chara["talent_level"], 1)
        val unlocked = HashSet<Int>(innate[cardId] ?: emptySet())
        for ((needRank, sid) in awakening[cardId] ?: emptyList()) {
            if (talentLevel >= needRank && sid > 0) unlocked.add(sid)
        }
        return unlocked
    }

    fun optimal(chara: Map<String, Any?>): List<Int> {
        val budget = JsonCodec.asInt(chara["skill_point"], 0)
        if (budget <= 0) return emptyList()
        val apts = aptitudes(chara)
        val ownedByGroup = HashMap<Int, SkillEntry>()
        for (item in JsonCodec.asList(chara["skill_array"]) ?: emptyList()) {
            val row = JsonCodec.asMap(item) ?: continue
            val entry = typedSkills[JsonCodec.asInt(row["skill_id"], 0)] ?: continue
            val prev = ownedByGroup[entry.groupId]
            if (prev == null || entry.groupRate > prev.groupRate) {
                ownedByGroup[entry.groupId] = entry
            }
        }
        val (hintGroup, hintSkill) = hints(chara)
        val effects = (JsonCodec.asList(chara["chara_effect_id_array"]) ?: emptyList())
            .mapNotNull { JsonCodec.asLongOrNull(it)?.toInt() }
            .toSet()
        val fastLearner = (7 in effects) || JsonCodec.asBool(chara["fast_learner"], false)
        val unlocked = unlockedCardSkills(chara)

        fun hintLevel(entry: SkillEntry): Int {
            val own = hintSkill[entry.skillId] ?: 0
            val grouped = hintGroup[entry.groupId to entry.rarity] ?: 0
            return maxOf(own, grouped).coerceIn(0, 5)
        }

        fun tierCost(entry: SkillEntry): Int {
            val discount = minOf(100, HINT_DISCOUNT[hintLevel(entry)] + if (fastLearner) 10 else 0)
            return maxOf(10, (entry.baseCost * (100 - discount)) / 100)
        }

        data class GroupOpt(val cost: Int, val net: Int, val chain: List<Int>)

        val options = mutableListOf<List<GroupOpt>>()
        for (entries in groups.values) {
            val owned = ownedByGroup[entries[0].groupId]
            val ownedRate = owned?.groupRate ?: 0
            val anyHint = entries.any { hintLevel(it) > 0 }
            val anyInnate = entries.any { it.skillId in unlocked }
            if (!anyHint && !anyInnate) continue
            val oldScore = if (owned != null) score(owned, apts) else 0
            val groupOptions = mutableListOf<GroupOpt>()
            var cumulative = 0
            val chain = mutableListOf<Int>()
            for (entry in entries) {
                if (entry.groupRate <= ownedRate) continue
                cumulative += tierCost(entry)
                chain.add(entry.skillId)
                val legal = if (entry.rarity == 1) {
                    anyHint || anyInnate
                } else {
                    hintLevel(entry) > 0 || entry.skillId in unlocked
                }
                if (!legal) continue
                val net = score(entry, apts) - oldScore
                if (net > 0 && cumulative <= budget) {
                    groupOptions.add(GroupOpt(cumulative, net, chain.toList()))
                }
            }
            if (groupOptions.isNotEmpty()) {
                options.add(groupOptions)
            }
        }
        if (options.isEmpty()) return emptyList()

        var best = IntArray(budget + 1) { -1 }
        best[0] = 0
        val parents = mutableListOf<HashMap<Int, Pair<Int, List<Int>>>>()
        for (groupOpts in options) {
            val nxt = best.copyOf()
            val choices = HashMap<Int, Pair<Int, List<Int>>>()
            for (spent in 0..budget) {
                val base = best[spent]
                if (base < 0) continue
                for (opt in groupOpts) {
                    val total = spent + opt.cost
                    if (total <= budget && base + opt.net > nxt[total]) {
                        nxt[total] = base + opt.net
                        choices[total] = spent to opt.chain
                    }
                }
            }
            best = nxt
            parents.add(choices)
        }

        var bestSpent = 0
        var bestValue = 0
        for (spent in 0..budget) {
            if (best[spent] > bestValue) {
                bestValue = best[spent]
                bestSpent = spent
            }
        }
        if (bestValue <= 0) return emptyList()

        val chosen = mutableListOf<Int>()
        var cur = bestSpent
        for (idx in options.indices.reversed()) {
            val choice = parents[idx][cur] ?: continue
            chosen.addAll(choice.second.asReversed())
            cur = choice.first
        }
        chosen.reverse()
        return chosen
    }

    fun bundle(chara: Map<String, Any?>?): List<Map<String, Int>> {
        if (chara == null) return emptyList()
        return runCatching { optimal(chara) }
            .getOrElse { emptyList() }
            .map { mapOf("skill_id" to it, "level" to 1) }
    }

    companion object {
        private val HINT_DISCOUNT = intArrayOf(0, 10, 20, 30, 35, 40)
        private val BRANCH_TOKEN = Regex("(distance_type|running_style)==([1-4])")
        private val APTITUDE_DEFAULTS = listOf(
            "proper_ground_turf" to 7,
            "proper_ground_dirt" to 1,
            "proper_distance_short" to 4,
            "proper_distance_mile" to 6,
            "proper_distance_middle" to 7,
            "proper_distance_long" to 6,
            "proper_running_style_nige" to 6,
            "proper_running_style_senko" to 7,
            "proper_running_style_sashi" to 7,
            "proper_running_style_oikomi" to 4,
        )
    }
}
