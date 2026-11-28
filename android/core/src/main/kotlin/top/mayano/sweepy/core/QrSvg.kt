package top.mayano.sweepy.core

import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import com.google.zxing.qrcode.encoder.Encoder

object QrSvg {
    fun renderQrSvg(text: String, border: Int = 4): String {
        require(border in 0..16) { "border out of range" }
        val hints = mapOf(EncodeHintType.CHARACTER_SET to "UTF-8")
        val code = Encoder.encode(text, ErrorCorrectionLevel.L, hints)
        val matrix = code.matrix
        val size = matrix.width
        val viewSize = size + 2 * border
        val path = StringBuilder(size * size * 8)
        for (rowIdx in 0 until matrix.height) {
            val yPos = rowIdx + border
            var colIdx = 0
            while (colIdx < size) {
                if (matrix.get(colIdx, rowIdx).toInt() == 0) {
                    colIdx++
                    continue
                }
                val startCol = colIdx
                while (colIdx < size && matrix.get(colIdx, rowIdx).toInt() != 0) {
                    colIdx++
                }
                val runWidth = colIdx - startCol
                val xPos = startCol + border
                path.append('M').append(xPos).append(' ').append(yPos)
                    .append('h').append(runWidth).append("v1h-").append(runWidth).append('z')
            }
        }
        return "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 $viewSize $viewSize\" " +
            "shape-rendering=\"crispEdges\">" +
            "<rect width=\"$viewSize\" height=\"$viewSize\" fill=\"white\"/>" +
            "<path d=\"$path\" fill=\"black\"/>" +
            "</svg>"
    }
}
