package top.mayano.sweepy.core

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.security.KeyPairGenerator
import java.security.interfaces.RSAPublicKey
import java.util.Base64
import javax.crypto.Cipher

internal fun findRepoRoot(): Path {
    var cur = Paths.get("").toAbsolutePath().normalize()
    repeat(8) {
        if (Files.isRegularFile(cur.resolve("public/index.html")) &&
            Files.isRegularFile(cur.resolve("sweepy/data/skill_catalog.json"))
        ) {
            return cur
        }
        cur = cur.parent ?: return@repeat
    }
    error("Could not locate repository root from ${Paths.get("").toAbsolutePath()}")
}

internal fun createRepoAssetSource(repoRoot: Path = findRepoRoot()): AssetSource = object : AssetSource {
    override fun readBytes(relativePath: String): ByteArray? {
        val clean = relativePath.trimStart('/')
        val candidates = listOf(
            repoRoot.resolve("public").resolve(clean),
            repoRoot.resolve("sweepy/data").resolve(clean),
        )
        for (p in candidates) {
            if (Files.isRegularFile(p)) return Files.readAllBytes(p)
        }
        return null
    }
}

class ParityVectorsTest {
    private val vectors: Map<String, Any?> by lazy {
        val stream = javaClass.getResourceAsStream("/parity_vectors.json")
            ?: error("Missing test resource /parity_vectors.json")
        stream.use { JsonCodec.decodeMap(it.readBytes().toString(Charsets.UTF_8)) }
    }

    @Test
    fun `crypto constants sid pack and unpack match python vectors`() {
        val c = JsonCodec.asMap(vectors["crypto"])!!
        assertEquals(c["salt_utf8"], UmaCrypto.SALT.toString(Charsets.US_ASCII))
        assertEquals(c["head_hex"], UmaCrypto.bytesToHex(UmaCrypto.HEAD))

        val udid = c["udid"].toString()
        val udidRaw = UmaCrypto.getRawUdid(udid)
        val sid0 = UmaCrypto.makeSid("0", udid)
        val sid1 = UmaCrypto.nextSid(sid0)
        val sidVid = UmaCrypto.makeSid("123456789", udid)

        assertEquals(c["sid0_hex"], UmaCrypto.bytesToHex(sid0))
        assertEquals(c["sid1_hex"], UmaCrypto.bytesToHex(sid1))
        assertEquals(c["sid_vid_hex"], UmaCrypto.bytesToHex(sidVid))
        assertEquals(c["steam_id_hash"], DeviceIdentity.computeSteamIdHash(c["steam_id"].toString()))
        assertEquals(c["machine_id_hex"], UmaCrypto.bytesToHex(ProtoWire.steamMachineId(c["steam_id"].toString())))

        val wireAnon = c["wire_anon_b64"].toString().toByteArray(Charsets.US_ASCII)
        val unpackedAnon = UmaCrypto.unpack(wireAnon, udid)
        val expectedAnon = JsonCodec.asMap(c["payload_anon"])!!
        assertEquals(expectedAnon, unpackedAnon.payload)
        assertNotNull(unpackedAnon.protocolHeader)
        assertEquals(UmaCrypto.HEAD.size + 16 + 16 + 32, unpackedAnon.protocolHeader!!.size)
        assertNull(UmaCrypto.issuedAuthFromHeader(unpackedAnon.protocolHeader))

        val authBytes = UmaCrypto.hexToBytes(c["auth_hex"].toString())
        val wireAuth = c["wire_auth_b64"].toString().toByteArray(Charsets.US_ASCII)
        val unpackedAuth = UmaCrypto.unpack(wireAuth, udid)
        val expectedAuth = JsonCodec.asMap(c["payload_auth"])!!
        assertEquals(expectedAuth, unpackedAuth.payload)
        assertArrayEquals(authBytes, UmaCrypto.issuedAuthFromHeader(unpackedAuth.protocolHeader))

        val kotlinPacked = UmaCrypto.pack(sidVid, udidRaw, authBytes, expectedAuth, udid)
        val kotlinUnpacked = UmaCrypto.unpack(kotlinPacked, udid)
        assertEquals(expectedAuth, kotlinUnpacked.payload)
        assertArrayEquals(authBytes, UmaCrypto.issuedAuthFromHeader(kotlinUnpacked.protocolHeader))
        val b64Bytes = Base64.getDecoder().decode(kotlinPacked.toString(Charsets.US_ASCII))
        assertTrue(b64Bytes.size > 168)
    }

    @Test
    fun `race binary decoder matches all 12 trace races`() {
        val cases = JsonCodec.asList(vectors["race_cases"])!!
        assertEquals(12, cases.size)
        for ((idx, item) in cases.withIndex()) {
            val row = JsonCodec.asMap(item)!!
            val smCid = JsonCodec.asLong(row["single_mode_chara_id"])
            val scen = row["race_scenario"] as String
            val horses = JsonCodec.asList(row["race_horse_data"])!!
            val expectedRank = JsonCodec.asInt(row["expected_rank"])
            assertEquals(expectedRank, RaceDecoder.decodePlayerRank(scen, horses, smCid), "Race vector #$idx mismatch")
        }
    }

    @Test
    fun `state stripper strips PII and matches all 3 golden fixtures`() {
        val cases = JsonCodec.asList(vectors["stripper_cases"])!!
        assertEquals(3, cases.size)
        for ((idx, item) in cases.withIndex()) {
            val row = JsonCodec.asMap(item)!!
            val input = JsonCodec.asMap(row["input"])!!
            val expected = JsonCodec.asMap(row["expected"])!!
            val stripped = StateStripper.stripCareerState(input)
            assertEquals(expected, stripped, "Stripper vector #$idx (${row["endpoint"]}) mismatch")
            val json = JsonCodec.encode(stripped).lowercase()
            assertFalse("secrettrainer" in json, "trainerName leaked in stripped #$idx")
            assertFalse("999888" in json, "viewerId leaked in stripped #$idx")
            assertFalse("76561198000000001" in json, "steam_id leaked in stripped #$idx")
        }
    }

    @Test
    fun `skill shop optimal solver matches python skill vectors and catalog`() {
        val catalog = Catalog(createRepoAssetSource())
        val shop = catalog.skillShop ?: error("Failed to load skill_catalog.json")
        val cases = JsonCodec.asList(vectors["skill_cases"])!!
        assertEquals(2, cases.size)
        for ((idx, item) in cases.withIndex()) {
            val row = JsonCodec.asMap(item)!!
            val chara = JsonCodec.asMap(row["chara"])!!
            val expectedIds = JsonCodec.asList(row["expected"])!!.map { JsonCodec.asInt(it) }
            val actualIds = shop.optimal(chara)
            assertEquals(expectedIds, actualIds, "Skill vector #$idx mismatch")
            val bundle = shop.bundle(chara)
            assertEquals(
                expectedIds.map { mapOf("skill_id" to it, "level" to 1) },
                bundle,
            )
        }
        assertEquals("Special Week", catalog.charaName(100101))
    }

    @Test
    fun `protobuf and steam ticket bytes match python encoders`() {
        val p = JsonCodec.asMap(vectors["proto"])!!

        val gcToken = ByteArray(16) { (it + 1).toByte() }
        val nonce = UmaCrypto.hexToBytes("1122334455667788")
        val webTicket = SteamTicketProvider.buildWebapiAuthTicket(gcToken, 3, 4567, nonce)
        assertEquals(p["webapi_ticket_hex"], UmaCrypto.bytesToHex(webTicket))

        val helloPkt = ProtoWire.packCmPacket(
            ProtoWire.EMSG_CLIENT_HELLO,
            ProtoWire.ProtoBufHeader(),
            ProtoWire.encodeClientHello(65580),
        )
        assertEquals(p["hello_pkt_hex"], UmaCrypto.bytesToHex(helloPkt))
        val unpackedHello = ProtoWire.unpackCmPacket(helloPkt)
        assertEquals(ProtoWire.EMSG_CLIENT_HELLO, unpackedHello.emsg)

        val pyQrFields = ProtoWire.decodeFields(UmaCrypto.hexToBytes(p["qr_req_hex"].toString()))
        val ktQrFields = ProtoWire.decodeFields(ProtoWire.encodeBeginQrRequest())
        assertEquals(ProtoWire.lastVarint(pyQrFields[2]), ProtoWire.lastVarint(ktQrFields[2]))
        val pyDev = ProtoWire.decodeFields(ProtoWire.lastBytes(pyQrFields[3])!!)
        val ktDev = ProtoWire.decodeFields(ProtoWire.lastBytes(ktQrFields[3])!!)
        assertEquals("Sweepy Android Client", ProtoWire.lastStr(ktDev[1]))
        assertEquals(ProtoWire.lastVarint(pyDev[2]), ProtoWire.lastVarint(ktDev[2]))
        assertEquals(ProtoWire.lastVarint(pyDev[3]), ProtoWire.lastVarint(ktDev[3]))
        assertEquals(ProtoWire.lastVarint(pyDev[4]), ProtoWire.lastVarint(ktDev[4]))

        val logonPkt = ProtoWire.packCmPacket(
            ProtoWire.EMSG_CLIENT_LOGON,
            ProtoWire.ProtoBufHeader(
                steamid = 76561198000000001L,
                clientSessionid = 0,
                jobidSource = -1L,
                jobidTarget = -1L,
            ),
            ProtoWire.encodeClientLogon(
                accessToken = "eyJhbGciOiJFZERTQSJ9.e30.sig",
                steamId = "76561198000000001",
            ),
        )
        assertEquals(p["logon_pkt_hex"], UmaCrypto.bytesToHex(logonPkt))
        val unpackedLogon = ProtoWire.unpackCmPacket(logonPkt)
        assertEquals(ProtoWire.EMSG_CLIENT_LOGON, unpackedLogon.emsg)
        assertEquals(76561198000000001L, unpackedLogon.header.steamid)

        val authListBody = ProtoWire.encodeAuthList(
            tokensLeft = 5,
            lastReqSeq = 0,
            lastServerSeq = 0,
            ticketCrc = 0xDEADBEEF.toInt(),
            authTicket = webTicket,
            appId = SteamTicketProvider.APP_ID,
            hSteamPipe = 42,
            serverSecret = SteamTicketProvider.SERVER_SECRET,
            msgSeq = 1,
        )
        assertEquals(p["auth_list_body_hex"], UmaCrypto.bytesToHex(authListBody))
    }

    @Test
    fun `qr svg renders valid crisp vector markup`() {
        val svg = QrSvg.renderQrSvg("https://s.team/q/1/abcd1234")
        assertTrue(svg.startsWith("<svg "))
        assertTrue("viewBox=\"" in svg)
        assertTrue("<path d=\"M" in svg)
        assertTrue(svg.endsWith("</svg>"))
    }

    @Test
    fun `msgpack uint64 above Long MAX_VALUE unpacks safely`() {
        val raw = UmaCrypto.hexToBytes("81a3753634cf8000000000000005")
        val decoded = UmaCrypto.unpackMsgPack(raw) as Map<*, *>
        assertEquals("9223372036854775813", decoded["u64"].toString())
    }

    @Test
    fun `credentials rsa encryption and steam guard protobufs roundtrip`() {
        val gen = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }
        val kp = gen.generateKeyPair()
        val pub = kp.public as RSAPublicKey
        val modHex = pub.modulus.toString(16)
        val expHex = pub.publicExponent.toString(16)
        val secret = "SecretPass!123"
        val encB64 = SteamTicketProvider.encryptPasswordRsa(secret, modHex, expHex)
        val cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
        cipher.init(Cipher.DECRYPT_MODE, kp.private)
        assertEquals(secret, cipher.doFinal(Base64.getDecoder().decode(encB64)).toString(Charsets.UTF_8))

        val rsaReq = ProtoWire.decodeFields(ProtoWire.encodeGetPasswordRsaKeyRequest("tester_acct"))
        assertEquals("tester_acct", ProtoWire.lastStr(rsaReq[1]))

        val credReq = ProtoWire.decodeFields(
            ProtoWire.encodeBeginCredentialsRequest("tester_acct", encB64, 987654321L)
        )
        assertEquals("tester_acct", ProtoWire.lastStr(credReq[2]))
        assertEquals(encB64, ProtoWire.lastStr(credReq[3]))
        assertEquals(987654321L, ProtoWire.lastVarint(credReq[4]))
        assertEquals("Client", ProtoWire.lastStr(credReq[8]))

        val confBytes = ByteArrayOutputStream().apply {
            ProtoWire.writeUint32Field(1, SteamTicketProvider.GUARD_EMAIL_CODE, this)
            ProtoWire.writeStrField(2, "user@example.com", this)
        }.toByteArray()
        val credRespRaw = ByteArrayOutputStream().apply {
            ProtoWire.writeVarintField(1, 555666L, this)
            ProtoWire.writeBytesField(2, byteArrayOf(1, 2, 3), this)
            ProtoWire.writeFloatField(3, 4.0f, this)
            ProtoWire.writeBytesField(4, confBytes, this)
            ProtoWire.writeVarintField(5, 76561198000000001L, this)
        }.toByteArray()
        val parsed = ProtoWire.BeginCredentialsResponse.decode(credRespRaw)
        assertEquals(555666L, parsed.clientId)
        assertEquals(76561198000000001L, parsed.steamId)
        assertEquals(1, parsed.allowedConfirmations.size)
        assertEquals(SteamTicketProvider.GUARD_EMAIL_CODE, parsed.allowedConfirmations[0].confirmationType)
        assertEquals("user@example.com", parsed.allowedConfirmations[0].associatedMessage)

        val guardReq = ProtoWire.decodeFields(
            ProtoWire.encodeUpdateSteamGuardCodeRequest(555666L, 76561198000000001L, "AB12C", 3)
        )
        assertEquals(555666L, ProtoWire.lastVarint(guardReq[1]))
        assertEquals(76561198000000001L, ProtoWire.lastFixed64(guardReq[2]))
        assertEquals("AB12C", ProtoWire.lastStr(guardReq[3]))
        assertEquals(3L, ProtoWire.lastVarint(guardReq[4]))

        val highBitClientId = java.lang.Long.parseUnsignedLong("11785782808063874333")
        assertTrue(highBitClientId < 0L)
        val highCredResp = ByteArrayOutputStream().apply {
            ProtoWire.writeVarintField(1, highBitClientId, this)
            ProtoWire.writeBytesField(2, byteArrayOf(9, 8, 7), this)
            ProtoWire.writeFloatField(3, 5.0f, this)
            ProtoWire.writeVarintField(5, 76561198000000001L, this)
        }.toByteArray()
        val decodedHighCred = ProtoWire.BeginCredentialsResponse.decode(highCredResp)
        assertEquals(highBitClientId, decodedHighCred.clientId)
        val pollEncoded = ProtoWire.decodeFields(
            ProtoWire.encodePollStatusRequest(highBitClientId, byteArrayOf(9, 8, 7))
        )
        assertEquals(highBitClientId, ProtoWire.lastVarint(pollEncoded[1]))
    }
}
