package top.mayano.sweepy.core

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonParser
import com.google.gson.ToNumberPolicy
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type

object JsonCodec {
    val gson: Gson = GsonBuilder()
        .setObjectToNumberStrategy(ToNumberPolicy.LONG_OR_DOUBLE)
        .disableHtmlEscaping()
        .create()

    val gsonPretty: Gson = GsonBuilder()
        .setObjectToNumberStrategy(ToNumberPolicy.LONG_OR_DOUBLE)
        .disableHtmlEscaping()
        .setPrettyPrinting()
        .create()

    private val mapType: Type = object : TypeToken<LinkedHashMap<String, Any?>>() {}.type

    fun encode(value: Any?): String = gson.toJson(value)

    fun encodePretty(value: Any?): String = gsonPretty.toJson(value) + "\n"

    @Suppress("UNCHECKED_CAST")
    fun decodeMap(text: String): MutableMap<String, Any?> {
        val elem = JsonParser.parseString(text)
        if (!elem.isJsonObject) {
            throw IllegalArgumentException("JSON root is not an object")
        }
        return (gson.fromJson<Any?>(elem, mapType) as? MutableMap<String, Any?>)
            ?: linkedMapOf()
    }

    fun decodeAny(text: String): Any? {
        val elem = JsonParser.parseString(text)
        return gson.fromJson<Any?>(elem, Any::class.java)
    }

    @Suppress("UNCHECKED_CAST")
    fun asMap(value: Any?): Map<String, Any?>? = value as? Map<String, Any?>

    @Suppress("UNCHECKED_CAST")
    fun asMutableMap(value: Any?): MutableMap<String, Any?>? = when (value) {
        is MutableMap<*, *> -> value as MutableMap<String, Any?>
        is Map<*, *> -> LinkedHashMap<String, Any?>().apply {
            for ((k, v) in value) {
                if (k != null) put(k.toString(), v)
            }
        }
        else -> null
    }

    @Suppress("UNCHECKED_CAST")
    fun asList(value: Any?): List<Any?>? = value as? List<Any?>

    fun asLongOrNull(value: Any?): Long? = when (value) {
        null, is Boolean -> null
        is Byte -> value.toLong()
        is Short -> value.toLong()
        is Int -> value.toLong()
        is Long -> value
        is Float -> if (value.isFinite()) value.toLong() else null
        is Double -> if (value.isFinite()) value.toLong() else null
        is Number -> value.toLong()
        is String -> {
            val s = value.trim()
            if (s.isEmpty()) null else s.toLongOrNull() ?: s.toDoubleOrNull()?.takeIf { it.isFinite() }?.toLong()
        }
        else -> null
    }

    fun asInt(value: Any?, default: Int = 0): Int = asLongOrNull(value)?.toInt() ?: default

    fun asLong(value: Any?, default: Long = 0L): Long = asLongOrNull(value) ?: default

    fun asDouble(value: Any?, default: Double = 0.0): Double = when (value) {
        null, is Boolean -> default
        is Number -> value.toDouble().takeIf { it.isFinite() } ?: default
        is String -> value.trim().toDoubleOrNull()?.takeIf { it.isFinite() } ?: default
        else -> default
    }

    fun asBool(value: Any?, default: Boolean = false): Boolean = when (value) {
        null -> default
        is Boolean -> value
        is Number -> value.toDouble() != 0.0
        is String -> value.trim().lowercase() in setOf("1", "true", "yes", "on", "enabled")
        else -> default
    }

    fun asString(value: Any?, default: String = ""): String = when (value) {
        null -> default
        is String -> value
        else -> value.toString()
    }

    @Suppress("UNCHECKED_CAST")
    fun deepCopy(value: Any?): Any? = when (value) {
        is Map<*, *> -> LinkedHashMap<String, Any?>(value.size).apply {
            for ((k, v) in value) {
                if (k != null) put(k.toString(), deepCopy(v))
            }
        }
        is List<*> -> ArrayList<Any?>(value.size).apply {
            for (item in value) add(deepCopy(item))
        }
        is ByteArray -> value.copyOf()
        else -> value
    }
}
