package top.mayano.sweepy.core

import org.msgpack.core.MessageBufferPacker
import org.msgpack.core.MessageFormat
import org.msgpack.core.MessagePack
import org.msgpack.core.MessageUnpacker
import org.msgpack.value.ValueType
import java.io.ByteArrayOutputStream
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

data class UnpackedEnvelope(
    val payload: Any?,
    val protocolHeader: ByteArray?,
)

object UmaCrypto {
    val SALT: ByteArray = "co!=Y;(UQCGxJ_n82".toByteArray(Charsets.US_ASCII)
    val HEAD: ByteArray = hexToBytes(
        "6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb3" +
            "44bdb7270a9067f5b63cd61f152cfb986cbfbf7a"
    )

    private val rng = SecureRandom()
    private val AUTH_HEX_RE = Regex("^[0-9a-fA-F]{96}$")
    private val AUTH_KEY_NAME_RE = Regex("auth.*key|newauthkey", RegexOption.IGNORE_CASE)

    fun hexToBytes(hex: String): ByteArray {
        val clean = hex.trim()
        require(clean.length % 2 == 0) { "Odd hex length: ${clean.length}" }
        return ByteArray(clean.length / 2) { i ->
            clean.substring(i * 2, i * 2 + 2).toInt(16).toByte()
        }
    }

    fun bytesToHex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    fun sm5(data: ByteArray): ByteArray {
        val md = MessageDigest.getInstance("MD5")
        md.update(data)
        md.update(SALT)
        return md.digest()
    }

    fun makeSid(viewerId: String, udid: String): ByteArray =
        sm5((viewerId + udid).toByteArray(Charsets.UTF_8))

    fun nextSid(sid: ByteArray): ByteArray = sm5(sid)

    fun nextSid(sidText: String): ByteArray = sm5(sidText.toByteArray(Charsets.UTF_8))

    fun genKey(): ByteArray {
        val out = ByteArrayOutputStream(40)
        while (out.size() < 32) {
            val s = rng.nextInt(65536).toString(16).toByteArray(Charsets.US_ASCII)
            out.write(s)
        }
        return out.toByteArray().copyOfRange(0, 32)
    }

    fun getIv(udid: String): ByteArray =
        udid.replace("-", "").lowercase().substring(0, 16).toByteArray(Charsets.US_ASCII)

    fun getRawUdid(udid: String): ByteArray =
        hexToBytes(udid.replace("-", "").lowercase())

    fun pack(
        sid: ByteArray,
        udidRaw: ByteArray,
        auth: ByteArray,
        payload: Map<String, Any?>,
        udid: String,
    ): ByteArray {
        val key = genKey()
        val msgBytes = packMsgPack(payload)
        val plain = ByteBuffer.allocate(4 + msgBytes.size).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(msgBytes.size)
            .put(msgBytes)
            .array()

        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(getIv(udid)))
        val encrypted = cipher.doFinal(plain)
        val body = encrypted + key

        val nonce = ByteArray(32).also { rng.nextBytes(it) }
        val hdrOut = ByteArrayOutputStream(164)
        hdrOut.write(HEAD)
        hdrOut.write(sid)
        hdrOut.write(udidRaw)
        hdrOut.write(nonce)
        if (auth.isNotEmpty()) {
            hdrOut.write(auth)
        }
        val hdr = hdrOut.toByteArray()

        val full = ByteBuffer.allocate(4 + hdr.size + body.size).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(hdr.size)
            .put(hdr)
            .put(body)
            .array()
        return Base64.getEncoder().encode(full)
    }

    fun unpack(rawResponse: ByteArray, udid: String): UnpackedEnvelope {
        val cleanText = rawResponse.toString(Charsets.UTF_8).trim()
        val raw = try {
            Base64.getDecoder().decode(cleanText)
        } catch (exc: Exception) {
            throw StateRecoveryException("Malformed base64 UMA envelope", cause = exc)
        }
        var protocolHeader: ByteArray? = null
        var bodyBytes = raw
        if (raw.size >= 4) {
            val hdrLen = ByteBuffer.wrap(raw, 0, 4).order(ByteOrder.LITTLE_ENDIAN).int
            val hdrEnd = 4 + hdrLen
            val minHdr = HEAD.size + 16 + 16 + 32
            if (
                hdrLen in minHdr..2048 &&
                hdrEnd + 32 <= raw.size &&
                (raw.size - hdrEnd - 32) % 16 == 0 &&
                raw.copyOfRange(4, 4 + HEAD.size).contentEquals(HEAD)
            ) {
                protocolHeader = raw.copyOfRange(4, hdrEnd)
                bodyBytes = raw.copyOfRange(hdrEnd, raw.size)
            }
        }
        if (bodyBytes.size < 48 || (bodyBytes.size - 32) % 16 != 0) {
            throw StateRecoveryException("Malformed UMA envelope length")
        }
        val key = bodyBytes.copyOfRange(bodyBytes.size - 32, bodyBytes.size)
        val cipherBytes = bodyBytes.copyOfRange(0, bodyBytes.size - 32)
        val plain = try {
            val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(getIv(udid)))
            cipher.doFinal(cipherBytes)
        } catch (exc: Exception) {
            throw StateRecoveryException("UMA payload decryption failed", cause = exc)
        }
        if (plain.size < 4) {
            throw StateRecoveryException("UMA payload missing length prefix")
        }
        val msgLen = ByteBuffer.wrap(plain, 0, 4).order(ByteOrder.LITTLE_ENDIAN).int
        if (msgLen < 0 || 4 + msgLen > plain.size) {
            throw StateRecoveryException("UMA payload length exceeds frame")
        }
        val decoded = unpackMsgPack(plain, 4, msgLen)
        return UnpackedEnvelope(decoded, protocolHeader)
    }

    fun issuedAuthFromHeader(header: ByteArray?): ByteArray? {
        if (header == null || header.size != 164) return null
        if (!header.copyOfRange(0, HEAD.size).contentEquals(HEAD)) return null
        val tail = header.copyOfRange(header.size - 48, header.size)
        if (tail.all { it == 0.toByte() } || tail.all { it == 0xFF.toByte() }) return null
        return tail
    }

    fun authFromResponse(response: Any?, depth: Int = 0): ByteArray? {
        if (depth > 5 || response == null) return null
        when (response) {
            is Map<*, *> -> {
                for ((k, item) in response) {
                    if (k != null && AUTH_KEY_NAME_RE.containsMatchIn(k.toString())) {
                        when (item) {
                            is ByteArray -> {
                                if (item.size == 48 && !isSentinelAuth(item)) return item
                            }
                            is String -> {
                                val s = item.trim()
                                if (AUTH_HEX_RE.matches(s)) {
                                    val raw = hexToBytes(s)
                                    if (!isSentinelAuth(raw)) return raw
                                }
                                runCatching { Base64.getDecoder().decode(s) }.getOrNull()?.let { decoded ->
                                    if (decoded.size == 48 && !isSentinelAuth(decoded)) return decoded
                                }
                            }
                        }
                    }
                    authFromResponse(item, depth + 1)?.let { return it }
                }
            }
            is List<*> -> {
                val lim = minOf(32, response.size)
                for (i in 0 until lim) {
                    authFromResponse(response[i], depth + 1)?.let { return it }
                }
            }
        }
        return null
    }

    private fun isSentinelAuth(b: ByteArray): Boolean =
        b.all { it == 0.toByte() } || b.all { it == 0xFF.toByte() }

    fun packMsgPack(value: Any?): ByteArray {
        val packer = MessagePack.newDefaultBufferPacker()
        packValue(packer, value)
        packer.flush()
        return packer.toByteArray()
    }

    private fun packValue(packer: MessageBufferPacker, value: Any?) {
        when (value) {
            null -> packer.packNil()
            is Boolean -> packer.packBoolean(value)
            is Byte -> packer.packLong(value.toLong())
            is Short -> packer.packLong(value.toLong())
            is Int -> packer.packLong(value.toLong())
            is Long -> packer.packLong(value)
            is Float -> packer.packDouble(value.toDouble())
            is Double -> packer.packDouble(value)
            is Number -> packer.packLong(value.toLong())
            is String -> packer.packString(value)
            is ByteArray -> {
                packer.packBinaryHeader(value.size)
                packer.writePayload(value)
            }
            is Map<*, *> -> {
                packer.packMapHeader(value.size)
                for ((k, v) in value) {
                    packValue(packer, k?.toString() ?: "")
                    packValue(packer, v)
                }
            }
            is Collection<*> -> {
                packer.packArrayHeader(value.size)
                for (item in value) {
                    packValue(packer, item)
                }
            }
            is Array<*> -> {
                packer.packArrayHeader(value.size)
                for (item in value) {
                    packValue(packer, item)
                }
            }
            is IntArray -> {
                packer.packArrayHeader(value.size)
                for (item in value) packer.packInt(item)
            }
            is LongArray -> {
                packer.packArrayHeader(value.size)
                for (item in value) packer.packLong(item)
            }
            else -> packer.packString(value.toString())
        }
    }

    fun unpackMsgPack(bytes: ByteArray, offset: Int = 0, length: Int = bytes.size - offset): Any? {
        val unpacker = MessagePack.newDefaultUnpacker(bytes, offset, length)
        return unpackValue(unpacker)
    }

    private fun unpackValue(unpacker: MessageUnpacker): Any? {
        if (!unpacker.hasNext()) return null
        val fmt = unpacker.nextFormat
        return when (fmt.valueType) {
            ValueType.NIL -> {
                unpacker.unpackNil()
                null
            }
            ValueType.BOOLEAN -> unpacker.unpackBoolean()
            ValueType.INTEGER -> {
                if (fmt == MessageFormat.UINT64) {
                    val bi = unpacker.unpackBigInteger()
                    if (bi <= BigInteger.valueOf(Long.MAX_VALUE)) bi.toLong() else bi
                } else {
                    unpacker.unpackLong()
                }
            }
            ValueType.FLOAT -> unpacker.unpackDouble()
            ValueType.STRING -> unpacker.unpackString()
            ValueType.BINARY -> {
                val len = unpacker.unpackBinaryHeader()
                unpacker.readPayload(len)
            }
            ValueType.ARRAY -> {
                val len = unpacker.unpackArrayHeader()
                ArrayList<Any?>(len).apply {
                    repeat(len) { add(unpackValue(unpacker)) }
                }
            }
            ValueType.MAP -> {
                val len = unpacker.unpackMapHeader()
                LinkedHashMap<String, Any?>(len).apply {
                    repeat(len) {
                        val key = unpackValue(unpacker)?.toString() ?: ""
                        val v = unpackValue(unpacker)
                        put(key, v)
                    }
                }
            }
            ValueType.EXTENSION -> {
                val ext = unpacker.unpackExtensionTypeHeader()
                unpacker.readPayload(ext.length)
            }
        }
    }
}
