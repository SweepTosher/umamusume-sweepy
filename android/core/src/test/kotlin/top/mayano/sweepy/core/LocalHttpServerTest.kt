package top.mayano.sweepy.core

import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.ByteArrayInputStream
import java.net.Socket
import java.nio.file.Path
import java.util.zip.GZIPInputStream

class LocalHttpServerTest {
    private val testHttp = OkHttpClient()

    private fun rawHttpRequest(port: Int, rawText: String): Pair<Int, Pair<Map<String, String>, String>> {
        Socket("127.0.0.1", port).use { sock ->
            sock.soTimeout = 5000
            sock.getOutputStream().write(rawText.toByteArray(Charsets.ISO_8859_1))
            sock.getOutputStream().flush()
            val full = sock.getInputStream().readBytes().toString(Charsets.UTF_8)
            val split = full.indexOf("\r\n\r\n")
            val headText = if (split >= 0) full.substring(0, split) else full
            val body = if (split >= 0) full.substring(split + 4) else ""
            val lines = headText.split("\r\n")
            val status = lines[0].split(' ').getOrNull(1)?.toIntOrNull() ?: 0
            val hdrs = LinkedHashMap<String, String>()
            for (line in lines.drop(1)) {
                val c = line.indexOf(':')
                if (c > 0) hdrs[line.substring(0, c).trim().lowercase()] = line.substring(c + 1).trim()
            }
            return status to (hdrs to body)
        }
    }

    @Test
    fun `runtime store validates urls separates secrets and persists settings`(@TempDir tmp: Path) {
        val store = RuntimeStore(tmp.resolve("rt"))
        val salt1 = store.accountSalt()
        val salt2 = store.accountSalt()
        assertEquals(64, salt1.length)
        assertEquals(salt1, salt2)

        assertThrows(IllegalArgumentException::class.java) {
            validateBrainUrl("http://remote.example.com/sweepy")
        }
        assertEquals("https://mayano.top/sweepy", validateBrainUrl("https://mayano.top/sweepy/"))
        assertEquals("http://127.0.0.1:8787", validateBrainUrl("http://127.0.0.1:8787/"))

        val saved = store.setBrainConfig("https://mayano.top/sweepy", "secret-key-123456")
        assertEquals("secret-key-123456", saved.apiKey)
        assertTrue(store.apiKeyFile.toFile().isFile)
        val settingsDisk = store.settingsFile.toFile().readText()
        assertFalse("secret-key-123456" in settingsDisk)

        store.setTurnDelay(2.1, 4.4, false)
        assertEquals(2.1, store.loadSettings().turnDelay.min)
        assertEquals(4.4, store.loadSettings().turnDelay.max)
    }

    @Test
    fun `local http server serves shared ui enforces origin and host checks and handles settings`(@TempDir tmp: Path) {
        val store = RuntimeStore(tmp.resolve("rt"))
        SweepyEngine(store, createRepoAssetSource(), http = testHttp).use { engine ->
            LocalHttpServer(engine, requestedPort = 0).use { srv ->
                val base = srv.url

                val home = testHttp.newCall(Request.Builder().url("$base/").get().build()).execute()
                home.use { r ->
                    assertEquals(200, r.code)
                    assertEquals("nosniff", r.header("X-Content-Type-Options"))
                    assertEquals("DENY", r.header("X-Frame-Options"))
                    assertEquals("no-referrer", r.header("Referrer-Policy"))
                    assertNotEquals(null, r.header("Content-Security-Policy"))
                    val html = r.body.string()
                    assertTrue("qr-open-steam-btn" in html)
                    assertTrue("credentials-form" in html)
                    assertTrue("guard-panel" in html)
                    assertTrue("viewport-fit=cover" in html)
                }

                testHttp.newCall(Request.Builder().url("$base/styles.css").get().build()).execute().use { r ->
                    assertEquals(200, r.code)
                    assertTrue("@media (max-width: 960px)" in r.body.string())
                }

                testHttp.newCall(Request.Builder().url("$base/app.js").get().build()).execute().use { r ->
                    assertEquals(200, r.code)
                    val js = r.body.string()
                    assertTrue("setQrChallengeUrl" in js)
                    assertTrue("submitCredentialsLogin" in js)
                    assertTrue("Approve this sign-in using the Steam Mobile app." in js)
                }

                testHttp.newCall(Request.Builder().url("$base/api/session").get().build()).execute().use { r ->
                    assertEquals(200, r.code)
                    val parsed = JsonCodec.decodeMap(r.body.string())
                    assertEquals(true, parsed["ok"])
                    assertEquals(false, parsed["logged_in"])
                    assertEquals(true, parsed["password_auth"])
                    assertEquals(false, parsed["cm_enabled"])
                }

                val badHost = rawHttpRequest(
                    srv.port,
                    "GET /api/session HTTP/1.1\r\nHost: evil.example:8080\r\nConnection: close\r\n\r\n",
                )
                assertEquals(403, badHost.first)

                val badOrigin = rawHttpRequest(
                    srv.port,
                    "POST /api/logout HTTP/1.1\r\nHost: 127.0.0.1:${srv.port}\r\nOrigin: https://evil.example\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                assertEquals(403, badOrigin.first)

                val badFetchSite = rawHttpRequest(
                    srv.port,
                    "POST /api/logout HTTP/1.1\r\nHost: 127.0.0.1:${srv.port}\r\nSec-Fetch-Site: cross-site\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                assertEquals(403, badFetchSite.first)

                val badCt = testHttp.newCall(
                    Request.Builder()
                        .url("$base/api/settings/turn-delay")
                        .post("min=1".toRequestBody("text/plain".toMediaType()))
                        .build()
                ).execute()
                badCt.use { assertEquals(400, it.code) }

                val tdRes = testHttp.newCall(
                    Request.Builder()
                        .url("$base/api/settings/turn-delay")
                        .post("""{"min":2.0,"max":5.0,"disabled":false}""".toRequestBody("application/json".toMediaType()))
                        .build()
                ).execute()
                tdRes.use { r ->
                    assertEquals(200, r.code)
                    val m = JsonCodec.decodeMap(r.body.string())
                    assertEquals(2.0, JsonCodec.asDouble(m["min"]))
                    assertEquals(5.0, JsonCodec.asDouble(m["max"]))
                }

                val cmRes = testHttp.newCall(
                    Request.Builder()
                        .url("$base/api/settings/cm")
                        .post("""{"cm_mode":true}""".toRequestBody("application/json".toMediaType()))
                        .build()
                ).execute()
                cmRes.use { r ->
                    assertEquals(200, r.code)
                    val m = JsonCodec.decodeMap(r.body.string())
                    assertEquals(false, m["cm_enabled"])
                    assertEquals(false, JsonCodec.asMap(m["cm_config"])?.get("cm_mode"))
                }

                testHttp.newCall(Request.Builder().url("$base/api/career/final-turn-export").get().build()).execute().use { r ->
                    assertEquals(400, r.code)
                }

                testHttp.newCall(
                    Request.Builder()
                        .url("$base/api/auth/credentials/start")
                        .post("""{"username":"","password":""}""".toRequestBody("application/json".toMediaType()))
                        .build()
                ).execute().use { r ->
                    assertEquals(400, r.code)
                }

                testHttp.newCall(
                    Request.Builder()
                        .url("$base/api/auth/credentials/code")
                        .post("""{"code":"ABCDE"}""".toRequestBody("application/json".toMediaType()))
                        .build()
                ).execute().use { r ->
                    assertEquals(400, r.code)
                }
            }
        }
    }

    @Test
    fun `career runner executes encrypted uma turn captures final export and triggers download endpoint`(@TempDir tmp: Path) {
        val store = RuntimeStore(tmp.resolve("rt"))
        val udid = "749cc182-4824-4f40-bbee-63639c60aaca"
        val udidRaw = UmaCrypto.getRawUdid(udid)
        val authHex = "ab".repeat(48)
        val authBytes = UmaCrypto.hexToBytes(authHex)
        val viewerId = 123456789L
        val transitions = mutableListOf<Boolean>()
        var brainCalls = 0
        var lastStrippedSawTrainer = false

        val turn78Chara = linkedMapOf<String, Any?>(
            "single_mode_chara_id" to 77777L,
            "scenario_id" to 3,
            "card_id" to 100101,
            "turn" to 78,
            "playing_state" to 5,
            "vital" to 55,
            "max_vital" to 100,
            "motivation" to 5,
            "speed" to 1400,
            "stamina" to 900,
            "power" to 1100,
            "guts" to 700,
            "wiz" to 1050,
            "skill_point" to 320,
            "fans" to 250000,
            "talent_level" to 5,
            "race_running_style" to 2,
            "proper_distance_short" to 4,
            "proper_distance_mile" to 7,
            "proper_distance_middle" to 7,
            "proper_distance_long" to 6,
            "proper_running_style_nige" to 6,
            "proper_running_style_senko" to 7,
            "proper_running_style_sashi" to 5,
            "proper_running_style_oikomi" to 2,
            "proper_ground_turf" to 7,
            "proper_ground_dirt" to 1,
            "skill_array" to listOf(mapOf("skill_id" to 200011, "level" to 1)),
            "skill_tips_array" to listOf(mapOf("group_id" to 20011, "rarity" to 1, "level" to 2)),
        )

        val interceptor = Interceptor { chain ->
            val req = chain.request()
            val url = req.url.toString()
            if (url.startsWith("https://127.0.0.1:") || url.startsWith("http://127.0.0.1:")) {
                return@Interceptor chain.proceed(req)
            }
            if (url == "https://brain.test.invalid/sweepy/v1/gl/decide") {
                brainCalls++
                val buf = Buffer()
                req.body?.writeTo(buf)
                val bodyBytes = GZIPInputStream(ByteArrayInputStream(buf.readByteArray())).use { it.readBytes() }
                val bodyMap = JsonCodec.decodeMap(bodyBytes.toString(Charsets.UTF_8))
                assertTrue((bodyMap["viewer_id_hash"] as String).length == 64)
                if ("SecretTrainer" in JsonCodec.encode(bodyMap["state"])) {
                    lastStrippedSawTrainer = true
                }
                val (code, jsonOut) = if (brainCalls == 1) {
                    200 to """{"op":"rpc_step","params":{"endpoint":"single_mode_live/exec_command","payload":{"command_id":101,"current_turn":78}}}"""
                } else {
                    409 to """{"detail":"Career finished","code":"career_complete"}"""
                }
                return@Interceptor Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(code)
                    .message("OK")
                    .body(jsonOut.toResponseBody("application/json; charset=utf-8".toMediaType()))
                    .build()
            }
            if (url == "https://brain.test.invalid/sweepy/v1/gl/close") {
                return@Interceptor Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body("""{"ok":true}""".toResponseBody("application/json; charset=utf-8".toMediaType()))
                    .build()
            }
            if (url.startsWith("https://api.games.umamusume.com/umamusume/")) {
                val buf = Buffer()
                req.body?.writeTo(buf)
                val unpacked = UmaCrypto.unpack(buf.readByteArray(), udid)
                assertTrue(unpacked.payload is Map<*, *>)
                val respData = linkedMapOf<String, Any?>(
                    "response_code" to 1,
                    "data" to linkedMapOf(
                        "chara_info" to turn78Chara,
                        "home_info" to linkedMapOf("available_continue_num" to 3, "available_free_continue_num" to 0),
                        "live_data_set" to linkedMapOf(
                            "live_performance_info" to linkedMapOf("dance" to 10, "passion" to 10, "vocal" to 10, "visual" to 10, "mental" to 10),
                            "master_live_id_array" to listOf(101, 102),
                        ),
                        "command_result" to linkedMapOf("command_id" to 101, "result_state" to 1),
                        "unchecked_event_array" to emptyList<Any>(),
                        "race_condition_array" to emptyList<Any>(),
                    ),
                )
                val packedResp = UmaCrypto.pack(UmaCrypto.makeSid(viewerId.toString(), udid), udidRaw, authBytes, respData, udid)
                return@Interceptor Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body(packedResp.toResponseBody("application/x-msgpack".toMediaType()))
                    .build()
            }
            error("Unexpected URL in offline test: $url")
        }

        val offlineHttp = OkHttpClient.Builder().addInterceptor(interceptor).build()
        val timing = TimingDna(store.timingSeedFile, disabled = true)
        val umaClient = UmaClient(
            http = offlineHttp,
            udidStr = udid,
            deviceId = "ab".repeat(20),
            deviceName = "Windows PC",
            graphicsDevice = "Direct3D 11",
            ipAddress = "127.0.0.1",
            platformOs = DeviceIdentity.PORTABLE_WINDOWS_OS,
            viewerId = viewerId,
            authKeyHex = authHex,
            steamId = "76561198000000001",
            steamTicket = "",
            appVer = "1.35.5",
            resVer = "10008795",
            provider = null,
            timing = timing,
        )
        val brain = BrainClient("https://brain.test.invalid/sweepy", "test-api-key", offlineHttp)

        SweepyEngine(store, createRepoAssetSource(), http = offlineHttp) { active ->
            transitions.add(active)
        }.use { engine ->
            val initialState = linkedMapOf<String, Any?>(
                "chara_info" to turn78Chara,
                "home_info" to linkedMapOf(
                    "available_continue_num" to 3,
                    "command_info_array" to listOf(mapOf("command_id" to 101, "training_partner_array" to listOf(1, 2))),
                ),
                "trainerName" to "SecretTrainer",
                "unchecked_event_array" to emptyList<Any>(),
            )
            val isolatedRunner = CareerRunner(
                fastSleep = true,
                accountSalt = store.accountSalt(),
                runtimeDir = store.runtimeDir,
                catalog = engine.catalog,
            ) { active -> transitions.add(active) }
            val snap = isolatedRunner.runSync(umaClient, brain, initialState = initialState, maxSteps = 10)
            assertFalse(lastStrippedSawTrainer)
            assertEquals(true, snap["finished"])
            assertEquals("finished", snap["status"])
            assertEquals(false, snap["running"])
            assertEquals(true, snap["final_turn_export_ready"])
            assertEquals(listOf(true, false), transitions)

            val exp = isolatedRunner.finalTurnExport()!!
            assertEquals(78L, exp["turn"])
            val expJson = JsonCodec.asMap(exp["json"])!!
            assertEquals(100101L, JsonCodec.asMap(expJson["chara_info"])?.get("card_id"))

            val f = engine.runner.javaClass.getDeclaredField("_finalTurnPayload")
            f.isAccessible = true
            f.set(engine.runner, expJson)

            LocalHttpServer(engine, requestedPort = 0).use { srv ->
                offlineHttp.newCall(
                    Request.Builder().url("${srv.url}/api/career/final-turn-export?download=1").get().build()
                ).execute().use { r ->
                    assertEquals(200, r.code)
                    val cd = r.header("Content-Disposition").orEmpty()
                    assertTrue(cd.startsWith("attachment; filename=\"Special_Week_"))
                    assertTrue(cd.endsWith(".json\""))
                    val dlJson = JsonCodec.decodeMap(r.body.string())
                    assertEquals(100101L, JsonCodec.asMap(dlJson["chara_info"])?.get("card_id"))
                }
            }
        }
    }

    @Test
    fun `bootstrap falls back through pre_signup and signup when get_by_social_account returns no viewer_id`(@TempDir tmp: Path) {
        val store = RuntimeStore(tmp.resolve("rt"))
        val calledEndpoints = mutableListOf<String>()
        val authBytes = ByteArray(48) { (it + 1).toByte() }
        var capturedUdid = ""

        val interceptor = Interceptor { chain ->
            val req = chain.request()
            val url = req.url.toString()
            if (url == UmaClient.APP_LOOKUP_URL) {
                return@Interceptor Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body(
                        """{"resultCount":1,"results":[{"trackId":6480433538,"bundleId":"com.cygames.umamusume","version":"1.35.5"}]}"""
                            .toResponseBody("application/json; charset=utf-8".toMediaType())
                    )
                    .build()
            }
            if (url.startsWith(UmaClient.BASE_URL)) {
                val ep = url.removePrefix(UmaClient.BASE_URL)
                calledEndpoints.add(ep)
                val buf = Buffer()
                req.body?.writeTo(buf)
                val rawReqBytes = buf.readByteArray()
                if (capturedUdid.isEmpty()) {
                    val b64 = rawReqBytes.toString(Charsets.UTF_8)
                    val raw = java.util.Base64.getDecoder().decode(b64)
                    val udidSlice = raw.copyOfRange(4 + UmaCrypto.HEAD.size + 16, 4 + UmaCrypto.HEAD.size + 32)
                    val hex = UmaCrypto.bytesToHex(udidSlice)
                    capturedUdid = "${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20, 32)}"
                }
                val (respPayload, issuedAuth) = when (ep) {
                    UmaClient.PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT -> linkedMapOf<String, Any?>(
                        "response_code" to 1,
                        "data_headers" to linkedMapOf("result_code" to 1, "sid" to "probe_sid"),
                        "data" to linkedMapOf("resource_version" to "10008795"),
                    ) to ByteArray(0)
                    "account/get_by_social_account" -> linkedMapOf<String, Any?>(
                        "response_code" to 1,
                        "data_headers" to linkedMapOf("result_code" to 1, "sid" to "social_sid"),
                        "data" to linkedMapOf<String, Any?>(),
                    ) to ByteArray(0)
                    "tool/pre_signup" -> linkedMapOf<String, Any?>(
                        "response_code" to 1,
                        "data_headers" to linkedMapOf("result_code" to 1, "sid" to "pre_sid"),
                        "data" to linkedMapOf(
                            "enable_steam_account" to true,
                            "country_list" to listOf(mapOf("country" to "SG")),
                        ),
                    ) to ByteArray(0)
                    "tool/signup" -> {
                        val reqUnpacked = UmaCrypto.unpack(rawReqBytes, capturedUdid)
                        @Suppress("UNCHECKED_CAST")
                        val reqMap = reqUnpacked.payload as Map<String, Any?>
                        assertEquals("SG", reqMap["country"])
                        assertEquals("ABCDEF", reqMap["steam_session_ticket"])
                        linkedMapOf<String, Any?>(
                            "response_code" to 1,
                            "data_headers" to linkedMapOf("result_code" to 1, "viewer_id" to 888999111L, "sid" to "sign_sid"),
                            "data" to linkedMapOf("viewer_id" to 888999111L),
                        ) to authBytes
                    }
                    "tool/start_session" -> linkedMapOf<String, Any?>(
                        "response_code" to 1,
                        "data_headers" to linkedMapOf("result_code" to 1, "viewer_id" to 888999111L, "sid" to "start_sid"),
                        "data" to linkedMapOf("is_tutorial" to false),
                    ) to authBytes
                    "load/index" -> linkedMapOf<String, Any?>(
                        "response_code" to 1,
                        "data_headers" to linkedMapOf("result_code" to 1, "viewer_id" to 888999111L, "sid" to "load_sid"),
                        "data" to linkedMapOf("user_info" to linkedMapOf("name" to "SweepyTester", "tutorial_step" to 1000)),
                    ) to ByteArray(0)
                    else -> error("Unexpected UMA endpoint: $ep")
                }
                val packed = UmaCrypto.pack(
                    UmaCrypto.makeSid("0", capturedUdid),
                    UmaCrypto.getRawUdid(capturedUdid),
                    issuedAuth,
                    respPayload,
                    capturedUdid,
                )
                return@Interceptor Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body(packed.toResponseBody("application/x-msgpack".toMediaType()))
                    .build()
            }
            error("Unexpected URL: $url")
        }

        val offlineHttp = OkHttpClient.Builder().addInterceptor(interceptor).build()
        val (client, loadRes) = UmaClient.bootstrapWithTicket(
            store = store,
            http = offlineHttp,
            steamId = "76561198000000001",
            ticket = "ABCDEF",
            persistDevice = true,
        )
        client.use { c ->
            assertEquals(888999111L, c.viewerId)
            assertEquals(UmaCrypto.bytesToHex(authBytes), c.authKeyHex)
            assertEquals("10008795", c.resVer)
            assertTrue("tool/pre_signup" in calledEndpoints)
            assertTrue("tool/signup" in calledEndpoints)
            assertTrue("tool/start_session" in calledEndpoints)
            assertTrue("load/index" in calledEndpoints)
            assertEquals(1L, JsonCodec.asLong(loadRes["response_code"]))
            assertTrue(store.deviceFile.toFile().isFile)
        }
    }
}
