package top.mayano.sweepy.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

class ProtoException(message: String, cause: Throwable? = null) : IllegalArgumentException(message, cause)
class UnsupportedPacketException(message: String) : IllegalArgumentException(message)

object ProtoWire {
    const val WIRE_VARINT = 0
    const val WIRE_FIXED64 = 1
    const val WIRE_LEN = 2
    const val WIRE_FIXED32 = 5

    const val PROTO_MASK = 0x80000000.toInt()
    const val EMSG_MULTI = 1
    const val EMSG_SERVICE_METHOD_RESPONSE = 147
    const val EMSG_CLIENT_HEARTBEAT = 703
    const val EMSG_CLIENT_LOGON_RESPONSE = 751
    const val EMSG_CLIENT_GAME_CONNECT_TOKENS = 779
    const val EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET = 857
    const val EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE = 858
    const val EMSG_CLIENT_AUTH_LIST = 5432
    const val EMSG_CLIENT_LOGON = 5514
    const val EMSG_CLIENT_REQUEST_FREE_LICENSE = 5572
    const val EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE = 5573
    const val EMSG_CLIENT_AUTH_LIST_ACK = 5575
    const val EMSG_SERVICE_METHOD_CALL_FROM_CLIENT_NON_AUTHED = 9804
    const val EMSG_CLIENT_HELLO = 9805

    fun encodeVarint(value: Long, out: ByteArrayOutputStream) {
        var v = value
        while ((v ushr 7) != 0L) {
            out.write(((v.toInt() and 0x7F) or 0x80))
            v = v ushr 7
        }
        out.write(v.toInt() and 0x7F)
    }

    fun writeTag(fieldNumber: Int, wireType: Int, out: ByteArrayOutputStream) {
        require(fieldNumber > 0)
        encodeVarint((fieldNumber.toLong() shl 3) or wireType.toLong(), out)
    }

    fun writeVarintField(fieldNumber: Int, value: Long, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_VARINT, out)
        encodeVarint(value, out)
    }

    fun writeUint32Field(fieldNumber: Int, value: Int, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_VARINT, out)
        encodeVarint(value.toLong() and 0xFFFFFFFFL, out)
    }

    fun writeInt32Field(fieldNumber: Int, value: Int, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_VARINT, out)
        encodeVarint(value.toLong(), out)
    }

    fun writeBoolField(fieldNumber: Int, value: Boolean, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_VARINT, out)
        out.write(if (value) 1 else 0)
    }

    fun writeFixed32Field(fieldNumber: Int, value: Int, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_FIXED32, out)
        val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value).array()
        out.write(buf)
    }

    fun writeFixed64Field(fieldNumber: Int, value: Long, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_FIXED64, out)
        val buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value).array()
        out.write(buf)
    }

    fun writeFloatField(fieldNumber: Int, value: Float, out: ByteArrayOutputStream) {
        writeFixed32Field(fieldNumber, java.lang.Float.floatToRawIntBits(value), out)
    }

    fun writeBytesField(fieldNumber: Int, value: ByteArray, out: ByteArrayOutputStream) {
        writeTag(fieldNumber, WIRE_LEN, out)
        encodeVarint(value.size.toLong(), out)
        out.write(value)
    }

    fun writeStrField(fieldNumber: Int, value: String, out: ByteArrayOutputStream) {
        writeBytesField(fieldNumber, value.toByteArray(Charsets.UTF_8), out)
    }

    data class FieldEntry(val wireType: Int, val num: Long = 0L, val bytes: ByteArray = ByteArray(0))

    fun decodeFields(data: ByteArray, offset: Int = 0, length: Int = data.size - offset): Map<Int, List<FieldEntry>> {
        val fields = HashMap<Int, MutableList<FieldEntry>>()
        var pos = offset
        val end = offset + length
        fun readVarint(): Long {
            var res = 0L
            var shift = 0
            while (true) {
                if (pos >= end) throw ProtoException("Truncated varint")
                val b = data[pos++].toInt() and 0xFF
                res = res or ((b.toLong() and 0x7FL) shl shift)
                if ((b and 0x80) == 0) return res
                shift += 7
                if (shift > 63) throw ProtoException("Varint exceeds 10 bytes")
            }
        }
        while (pos < end) {
            val tag = readVarint()
            val fn = (tag ushr 3).toInt()
            val wt = (tag and 7L).toInt()
            if (fn <= 0) throw ProtoException("Invalid protobuf field number 0")
            val list = fields.getOrPut(fn) { mutableListOf() }
            when (wt) {
                WIRE_VARINT -> list.add(FieldEntry(wt, num = readVarint()))
                WIRE_FIXED64 -> {
                    if (pos + 8 > end) throw ProtoException("Truncated fixed64")
                    val v = ByteBuffer.wrap(data, pos, 8).order(ByteOrder.LITTLE_ENDIAN).long
                    pos += 8
                    list.add(FieldEntry(wt, num = v))
                }
                WIRE_LEN -> {
                    val len = readVarint().toInt()
                    if (len < 0 || pos + len > end) throw ProtoException("Truncated length field")
                    val chunk = data.copyOfRange(pos, pos + len)
                    pos += len
                    list.add(FieldEntry(wt, bytes = chunk))
                }
                WIRE_FIXED32 -> {
                    if (pos + 4 > end) throw ProtoException("Truncated fixed32")
                    val v = ByteBuffer.wrap(data, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xFFFFFFFFL
                    pos += 4
                    list.add(FieldEntry(wt, num = v))
                }
                else -> throw ProtoException("Unsupported protobuf wire type $wt")
            }
        }
        return fields
    }

    fun lastVarint(entries: List<FieldEntry>?): Long? = entries?.lastOrNull()?.also {
        if (it.wireType != WIRE_VARINT) throw ProtoException("Expected varint")
    }?.num

    fun lastFixed64(entries: List<FieldEntry>?): Long? = entries?.lastOrNull()?.also {
        if (it.wireType != WIRE_FIXED64) throw ProtoException("Expected fixed64")
    }?.num

    fun lastBytes(entries: List<FieldEntry>?): ByteArray? = entries?.lastOrNull()?.also {
        if (it.wireType != WIRE_LEN) throw ProtoException("Expected bytes")
    }?.bytes

    fun lastStr(entries: List<FieldEntry>?): String? = lastBytes(entries)?.toString(Charsets.UTF_8)

    fun lastFloat(entries: List<FieldEntry>?): Float? {
        val e = entries?.lastOrNull() ?: return null
        if (e.wireType != WIRE_FIXED32) throw ProtoException("Expected fixed32 float")
        return java.lang.Float.intBitsToFloat(e.num.toInt())
    }

    fun repeatedUint32(entries: List<FieldEntry>?): List<Long> {
        val out = mutableListOf<Long>()
        for (e in entries ?: emptyList()) {
            if (e.wireType == WIRE_VARINT) {
                out.add(e.num and 0xFFFFFFFFL)
            } else if (e.wireType == WIRE_LEN) {
                var p = 0
                while (p < e.bytes.size) {
                    var res = 0L
                    var sh = 0
                    while (true) {
                        val b = e.bytes[p++].toInt() and 0xFF
                        res = res or ((b.toLong() and 0x7FL) shl sh)
                        if ((b and 0x80) == 0) break
                        sh += 7
                    }
                    out.add(res and 0xFFFFFFFFL)
                }
            }
        }
        return out
    }

    fun repeatedBytes(entries: List<FieldEntry>?): List<ByteArray> =
        (entries ?: emptyList()).map {
            if (it.wireType != WIRE_LEN) throw ProtoException("Expected bytes")
            it.bytes
        }

    fun steamMachineId(accountIdentifier: String): ByteArray {
        val sha1 = MessageDigest.getInstance("SHA-1")
        fun digestAscii(label: String): ByteArray {
            sha1.reset()
            val src = "SteamUser Hash $label $accountIdentifier".toByteArray(Charsets.UTF_8)
            return sha1.digest(src).joinToString("") { "%02x".format(it) }.toByteArray(Charsets.US_ASCII)
        }
        fun ByteArrayOutputStream.cstr(s: String) {
            write(s.toByteArray(Charsets.US_ASCII))
            write(0)
        }
        val out = ByteArrayOutputStream(160)
        out.write(0)
        out.cstr("MessageObject")
        for (lbl in listOf("BB3", "FF2", "3B3")) {
            out.write(1)
            out.cstr(lbl)
            out.write(digestAscii(lbl))
            out.write(0)
        }
        out.write(8)
        out.write(8)
        val encoded = out.toByteArray()
        if (encoded.size != 155) throw ProtoException("Unexpected machine_id length ${encoded.size}")
        return encoded
    }

    data class ProtoBufHeader(
        val steamid: Long? = null,
        val clientSessionid: Int? = null,
        val routingAppid: Int? = null,
        val jobidSource: Long? = null,
        val jobidTarget: Long? = null,
        val targetJobName: String? = null,
        val eresult: Int? = null,
        val errorMessage: String? = null,
        val realm: Int? = null,
    ) {
        fun encode(): ByteArray {
            val out = ByteArrayOutputStream()
            steamid?.let { writeFixed64Field(1, it, out) }
            clientSessionid?.let { writeInt32Field(2, it, out) }
            routingAppid?.let { writeUint32Field(3, it, out) }
            jobidSource?.let { writeFixed64Field(10, it, out) }
            jobidTarget?.let { writeFixed64Field(11, it, out) }
            targetJobName?.let { writeStrField(12, it, out) }
            eresult?.let { writeInt32Field(13, it, out) }
            errorMessage?.let { writeStrField(14, it, out) }
            realm?.let { writeUint32Field(32, it, out) }
            return out.toByteArray()
        }

        companion object {
            fun decode(data: ByteArray): ProtoBufHeader {
                val f = decodeFields(data)
                return ProtoBufHeader(
                    steamid = lastFixed64(f[1]),
                    clientSessionid = lastVarint(f[2])?.toInt(),
                    routingAppid = lastVarint(f[3])?.toInt(),
                    jobidSource = lastFixed64(f[10]),
                    jobidTarget = lastFixed64(f[11]),
                    targetJobName = lastStr(f[12]),
                    eresult = lastVarint(f[13])?.toInt(),
                    errorMessage = lastStr(f[14]),
                    realm = lastVarint(f[32])?.toInt(),
                )
            }
        }
    }

    data class SteamPacket(val emsg: Int, val header: ProtoBufHeader, val body: ByteArray)

    fun packCmPacket(emsg: Int, header: ProtoBufHeader, body: ByteArray): ByteArray {
        val hdr = header.encode()
        return ByteBuffer.allocate(8 + hdr.size + body.size).order(ByteOrder.LITTLE_ENDIAN)
            .putInt((emsg and 0x7FFFFFFF) or PROTO_MASK)
            .putInt(hdr.size)
            .put(hdr)
            .put(body)
            .array()
    }

    fun unpackCmPacket(raw: ByteArray): SteamPacket {
        if (raw.size < 8) throw ProtoException("CM packet shorter than 8-byte header")
        val bb = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN)
        val rawEmsg = bb.int
        val hdrLen = bb.int
        if ((rawEmsg and PROTO_MASK) == 0) throw UnsupportedPacketException("Non-protobuf CM packet $rawEmsg")
        if (hdrLen < 0 || 8 + hdrLen > raw.size) throw ProtoException("CM header length exceeds frame")
        val hdr = ProtoBufHeader.decode(raw.copyOfRange(8, 8 + hdrLen))
        return SteamPacket(rawEmsg and 0x7FFFFFFF, hdr, raw.copyOfRange(8 + hdrLen, raw.size))
    }

    fun unpackMulti(body: ByteArray): List<ByteArray> {
        val f = decodeFields(body)
        val sizeUnzipped = (lastVarint(f[1]) ?: 0L).toInt()
        val rawBody = lastBytes(f[2]) ?: ByteArray(0)
        val payload = if (sizeUnzipped > 0) {
            val unzipped = GZIPInputStream(ByteArrayInputStream(rawBody)).use { it.readBytes() }
            if (unzipped.size != sizeUnzipped) throw ProtoException("CMsgMulti size mismatch")
            unzipped
        } else {
            rawBody
        }
        val packets = mutableListOf<ByteArray>()
        var pos = 0
        val bb = ByteBuffer.wrap(payload).order(ByteOrder.LITTLE_ENDIAN)
        while (pos < payload.size) {
            if (pos + 4 > payload.size) throw ProtoException("Truncated CMsgMulti packet len")
            val len = bb.getInt(pos)
            pos += 4
            if (len < 0 || pos + len > payload.size) throw ProtoException("Truncated CMsgMulti packet body")
            packets.add(payload.copyOfRange(pos, pos + len))
            pos += len
        }
        return packets
    }

    fun encodeClientHello(protocolVersion: Int = 65580): ByteArray =
        ByteArrayOutputStream().also { writeUint32Field(1, protocolVersion, it) }.toByteArray()

    fun encodeClientHeartBeat(): ByteArray = ByteArray(0)

    fun encodeClientLogon(accessToken: String, steamId: String): ByteArray {
        val out = ByteArrayOutputStream()
        writeUint32Field(1, 65580, out)
        writeStrField(6, "english", out)
        writeUint32Field(7, 4294967093L.toInt(), out)
        writeBoolField(8, true, out)
        val ipBytes = ByteArrayOutputStream().also { writeFixed32Field(1, 0, it) }.toByteArray()
        writeBytesField(11, ipBytes, out)
        writeBytesField(30, steamMachineId(steamId), out)
        writeUint32Field(33, 2, out)
        writeStrField(96, "", out)
        writeBoolField(102, true, out)
        if (accessToken.isNotEmpty()) writeStrField(108, accessToken, out)
        return out.toByteArray()
    }

    data class LogonResponse(val eresult: Int, val heartbeatSeconds: Int) {
        companion object {
            fun decode(data: ByteArray): LogonResponse {
                val f = decodeFields(data)
                val er = lastVarint(f[1])?.toInt() ?: 2
                val leg = lastVarint(f[2])?.toInt() ?: 0
                val hb = lastVarint(f[3])?.toInt() ?: 0
                return LogonResponse(er, if (hb > 0) hb else leg)
            }
        }
    }

    fun encodeDeviceDetails(deviceName: String = "Sweepy Android Client"): ByteArray =
        ByteArrayOutputStream().apply {
            writeStrField(1, deviceName, this)
            writeUint32Field(2, 1, this)
            writeInt32Field(3, -700, this)
            writeUint32Field(4, 1, this)
        }.toByteArray()

    fun encodeBeginQrRequest(): ByteArray =
        ByteArrayOutputStream().apply {
            writeUint32Field(2, 1, this)
            writeBytesField(3, encodeDeviceDetails(), this)
        }.toByteArray()

    fun encodeGetPasswordRsaKeyRequest(accountName: String): ByteArray =
        ByteArrayOutputStream().also { writeStrField(1, accountName, it) }.toByteArray()

    data class PasswordRsaKeyResponse(val modHex: String, val expHex: String, val timestamp: Long) {
        companion object {
            fun decode(data: ByteArray): PasswordRsaKeyResponse {
                val f = decodeFields(data)
                return PasswordRsaKeyResponse(
                    modHex = lastStr(f[1]) ?: "",
                    expHex = lastStr(f[2]) ?: "",
                    timestamp = lastVarint(f[3]) ?: 0L,
                )
            }
        }
    }

    fun encodeBeginCredentialsRequest(
        accountName: String,
        encryptedPassword: String,
        encryptionTimestamp: Long,
        deviceName: String = "Sweepy Android Client",
    ): ByteArray = ByteArrayOutputStream().apply {
        writeStrField(1, deviceName, this)
        writeStrField(2, accountName, this)
        writeStrField(3, encryptedPassword, this)
        writeVarintField(4, encryptionTimestamp, this)
        writeBoolField(5, true, this)
        writeUint32Field(6, 1, this)
        writeUint32Field(7, 1, this)
        writeStrField(8, "Client", this)
        writeBytesField(9, encodeDeviceDetails(deviceName), this)
    }.toByteArray()

    data class AllowedConfirmation(val confirmationType: Int, val associatedMessage: String) {
        companion object {
            fun decode(data: ByteArray): AllowedConfirmation {
                val f = decodeFields(data)
                return AllowedConfirmation(
                    confirmationType = (lastVarint(f[1]) ?: 0L).toInt(),
                    associatedMessage = lastStr(f[2]) ?: "",
                )
            }
        }
    }

    data class BeginCredentialsResponse(
        val clientId: Long,
        val requestId: ByteArray,
        val interval: Float,
        val allowedConfirmations: List<AllowedConfirmation>,
        val steamId: Long,
        val extendedErrorMessage: String,
    ) {
        companion object {
            fun decode(data: ByteArray): BeginCredentialsResponse {
                val f = decodeFields(data)
                val confs = repeatedBytes(f[4]).map { AllowedConfirmation.decode(it) }
                return BeginCredentialsResponse(
                    clientId = lastVarint(f[1]) ?: 0L,
                    requestId = lastBytes(f[2]) ?: ByteArray(0),
                    interval = lastFloat(f[3]) ?: 5f,
                    allowedConfirmations = confs,
                    steamId = lastVarint(f[5]) ?: 0L,
                    extendedErrorMessage = lastStr(f[8]) ?: "",
                )
            }
        }
    }

    fun encodeUpdateSteamGuardCodeRequest(
        clientId: Long,
        steamId: Long,
        code: String,
        codeType: Int,
    ): ByteArray = ByteArrayOutputStream().apply {
        writeVarintField(1, clientId, this)
        writeFixed64Field(2, steamId, this)
        writeStrField(3, code, this)
        writeUint32Field(4, codeType, this)
    }.toByteArray()

    data class BeginQrResponse(val clientId: Long, val challengeUrl: String, val requestId: ByteArray, val interval: Float) {
        companion object {
            fun decode(data: ByteArray): BeginQrResponse {
                val f = decodeFields(data)
                return BeginQrResponse(
                    clientId = lastVarint(f[1]) ?: 0L,
                    challengeUrl = lastStr(f[2]) ?: "",
                    requestId = lastBytes(f[3]) ?: ByteArray(0),
                    interval = lastFloat(f[4]) ?: 0f,
                )
            }
        }
    }

    fun encodePollStatusRequest(clientId: Long, requestId: ByteArray): ByteArray =
        ByteArrayOutputStream().apply {
            writeVarintField(1, clientId, this)
            writeBytesField(2, requestId, this)
        }.toByteArray()

    data class PollStatusResponse(
        val newClientId: Long,
        val newChallengeUrl: String,
        val refreshToken: String,
        val newGuardData: String,
        val hadRemoteInteraction: Boolean,
    ) {
        companion object {
            fun decode(data: ByteArray): PollStatusResponse {
                val f = decodeFields(data)
                return PollStatusResponse(
                    newClientId = lastVarint(f[1]) ?: 0L,
                    newChallengeUrl = lastStr(f[2]) ?: "",
                    refreshToken = lastStr(f[3]) ?: "",
                    newGuardData = lastStr(f[7]) ?: "",
                    hadRemoteInteraction = (lastVarint(f[5]) ?: 0L) != 0L,
                )
            }
        }
    }

    fun encodeGetAppOwnershipTicket(appId: Int): ByteArray =
        ByteArrayOutputStream().also { writeUint32Field(1, appId, it) }.toByteArray()

    data class OwnershipTicketResponse(val eresult: Int, val ticket: ByteArray) {
        companion object {
            fun decode(data: ByteArray): OwnershipTicketResponse {
                val f = decodeFields(data)
                return OwnershipTicketResponse(
                    eresult = lastVarint(f[1])?.toInt() ?: 2,
                    ticket = lastBytes(f[3]) ?: ByteArray(0),
                )
            }
        }
    }

    fun encodeRequestFreeLicense(appId: Int): ByteArray =
        ByteArrayOutputStream().also { writeUint32Field(2, appId, it) }.toByteArray()

    fun decodeRequestFreeLicenseResponseEresult(data: ByteArray): Int =
        lastVarint(decodeFields(data)[1])?.toInt() ?: 2

    fun decodeGameConnectTokens(data: ByteArray): List<ByteArray> =
        repeatedBytes(decodeFields(data)[2])

    fun encodeAuthList(
        tokensLeft: Int,
        lastReqSeq: Int,
        lastServerSeq: Int,
        ticketCrc: Int,
        authTicket: ByteArray,
        appId: Int,
        hSteamPipe: Int,
        serverSecret: ByteArray,
        msgSeq: Int,
    ): ByteArray {
        val ticketEntry = ByteArrayOutputStream().apply {
            writeUint32Field(1, 0, this)
            writeFixed64Field(3, 0L, this)
            writeFixed64Field(4, appId.toLong(), this)
            writeUint32Field(5, hSteamPipe, this)
            writeUint32Field(6, ticketCrc, this)
            writeBytesField(7, authTicket, this)
            if (serverSecret.isNotEmpty()) writeBytesField(8, serverSecret, this)
        }.toByteArray()
        return ByteArrayOutputStream().apply {
            writeUint32Field(1, tokensLeft, this)
            writeUint32Field(2, lastReqSeq, this)
            writeUint32Field(3, lastServerSeq, this)
            writeBytesField(4, ticketEntry, this)
            writeUint32Field(5, appId, this)
            writeUint32Field(6, msgSeq, this)
        }.toByteArray()
    }

    data class AuthListAck(val ticketCrcs: List<Long>, val messageSequence: Int) {
        companion object {
            fun decode(data: ByteArray): AuthListAck {
                val f = decodeFields(data)
                return AuthListAck(
                    ticketCrcs = repeatedUint32(f[1]),
                    messageSequence = (lastVarint(f[3]) ?: 0L).toInt(),
                )
            }
        }
    }
}
