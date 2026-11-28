package top.mayano.sweepy.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import java.util.zip.GZIPInputStream

object RaceDecoder {
    private const val MAX_SCENARIO_BYTES = 16 * 1024 * 1024

    fun decodePlayerRank(
        raceScenarioB64: String?,
        raceHorseData: List<Any?>?,
        singleModeCharaId: Long,
    ): Int {
        if (raceScenarioB64.isNullOrBlank()) {
            throw IllegalArgumentException("race_scenario_b64 is empty or not base64")
        }
        if (raceHorseData.isNullOrEmpty()) {
            throw IllegalArgumentException("race_horse_data is empty or not a list")
        }

        var runnerIdx: Int? = null
        for (item in raceHorseData) {
            val row = JsonCodec.asMap(item) ?: continue
            val rawCid = JsonCodec.asLongOrNull(row["single_mode_chara_id"]) ?: continue
            if (rawCid == singleModeCharaId) {
                val frameOrder = JsonCodec.asInt(row["frame_order"], -1)
                runnerIdx = frameOrder - 1
                break
            }
        }
        if (runnerIdx == null) {
            throw IllegalArgumentException("Player single_mode_chara_id $singleModeCharaId not found in race_horse_data")
        }

        val compressed = try {
            Base64.getDecoder().decode(raceScenarioB64.trim())
        } catch (exc: Exception) {
            throw IllegalArgumentException("race_scenario_b64 is not valid base64", exc)
        }

        val payload = try {
            GZIPInputStream(ByteArrayInputStream(compressed)).use { gz ->
                val out = ByteArrayOutputStream()
                val buf = ByteArray(16 * 1024)
                var total = 0
                while (true) {
                    val n = gz.read(buf)
                    if (n < 0) break
                    total += n
                    if (total > MAX_SCENARIO_BYTES) {
                        throw IllegalArgumentException("race_scenario payload exceeds $MAX_SCENARIO_BYTES bytes")
                    }
                    out.write(buf, 0, n)
                }
                out.toByteArray()
            }
        } catch (exc: IllegalArgumentException) {
            throw exc
        } catch (exc: Exception) {
            throw IllegalArgumentException("race_scenario_b64 is not gzip data", exc)
        }

        val bb = ByteBuffer.wrap(payload).order(ByteOrder.LITTLE_ENDIAN)
        var offset = 0
        fun requireBytes(count: Int, label: String) {
            if (count < 0 || offset.toLong() + count.toLong() > payload.size.toLong()) {
                throw IllegalArgumentException("Truncated $label at offset $offset")
            }
        }

        requireBytes(8, "version_header")
        val headerLength = bb.getInt(offset)
        offset += 8
        if (headerLength != 4) {
            throw IllegalArgumentException("Unsupported race_scenario header_length: $headerLength")
        }

        requireBytes(16, "race_header")
        val horseCount = bb.getInt(offset + 4)
        val resultStride = bb.getInt(offset + 12)
        offset += 16
        if (horseCount <= 0 || horseCount > 128) {
            throw IllegalArgumentException("Invalid horse_count: $horseCount")
        }
        if (resultStride < 4) {
            throw IllegalArgumentException("Invalid result_stride: $resultStride")
        }
        if (runnerIdx < 0 || runnerIdx >= horseCount) {
            throw IllegalArgumentException("runner_idx $runnerIdx out of range for horse_count $horseCount")
        }

        requireBytes(4, "pad_before_frames_len")
        val padFramesLen = bb.getInt(offset)
        offset += 4
        requireBytes(padFramesLen, "pad_before_frames")
        offset += padFramesLen

        requireBytes(8, "frame_section_header")
        val frameCount = bb.getInt(offset)
        val frameStride = bb.getInt(offset + 4)
        offset += 8
        if (frameCount < 0 || frameStride < 0) {
            throw IllegalArgumentException("Negative frame section dimensions")
        }
        val framesBytesLong = frameCount.toLong() * frameStride.toLong()
        if (framesBytesLong > payload.size.toLong() - offset.toLong()) {
            throw IllegalArgumentException("Truncated frame_section at offset $offset")
        }
        offset += framesBytesLong.toInt()

        requireBytes(4, "pad_before_results_len")
        val padResultsLen = bb.getInt(offset)
        offset += 4
        requireBytes(padResultsLen, "pad_before_results")
        offset += padResultsLen

        val resBytesLong = horseCount.toLong() * resultStride.toLong()
        if (resBytesLong > payload.size.toLong() - offset.toLong()) {
            throw IllegalArgumentException("Truncated result_section at offset $offset")
        }
        val targetOffset = offset + runnerIdx * resultStride
        val finishOrder = bb.getInt(targetOffset)
        val rank = finishOrder + 1
        if (rank !in 1..18) {
            throw IllegalArgumentException("Decoded player rank out of bounds: $rank")
        }
        return rank
    }
}
