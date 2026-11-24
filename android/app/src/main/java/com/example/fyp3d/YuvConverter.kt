package com.example.fyp3d

import java.nio.ByteBuffer

/**
 * YUV_420_888 to NV21 conversion, isolated from any Android type.
 *
 * WHY THIS IS A SEPARATE, PLATFORM-FREE FUNCTION
 * ==============================================
 * This is the one piece of Phase 4A that can fail SILENTLY. A stride mistake
 * still produces a decodable JPEG, so MiDaS returns a plausible-looking depth
 * map and nothing reports an error -- the fault only shows up if someone looks
 * at the uploaded image by eye. That makes it exactly the kind of code that
 * must be tested rather than reviewed.
 *
 * Taking ByteBuffers and strides instead of an `ImageProxy` keeps it runnable
 * in a plain JVM unit test (`app/src/test/.../YuvConverterTest.kt`), with no
 * device, no emulator and no Android mocking framework. The test feeds it
 * synthetic row-padded and semi-planar buffers whose correct output is known
 * by construction.
 *
 * WHAT THE RECOVERED IMPLEMENTATION GOT WRONG
 * ===========================================
 * The code recovered in commit 1ff73cb did, in effect:
 *
 *     yBuffer.get(nv21, 0, ySize)          // assumes rowStride == width
 *     ... interleave uBytes / vBytes ...   // assumes pixelStride == 1
 *
 * YUV_420_888 guarantees only the plane layout, never the packing:
 *
 *   - `rowStride` may exceed the image width because hardware aligns rows. A
 *     flat copy then pulls padding bytes into the image and the picture shears
 *     progressively further left/right down the frame.
 *   - the U and V planes are commonly SEMI-PLANAR: `pixelStride == 2`, both
 *     planes views into one interleaved allocation. Reading them as if they
 *     were tightly packed duplicates and swaps chroma, giving wrong colours.
 *
 * Hence the explicit per-row, per-pixel walk below.
 */
object YuvConverter {

    /**
     * Convert three YUV_420_888 planes into a single NV21 byte array.
     *
     * NV21 layout: the full-resolution Y plane, followed by one
     * half-resolution plane of interleaved **V,U** pairs (V first) -- which is
     * what [android.graphics.YuvImage] expects for `ImageFormat.NV21`.
     *
     * The buffers' positions are set explicitly per row, so the caller need
     * not rewind them first. [width] and [height] are expected to be even,
     * which is guaranteed for YUV_420_888 chroma subsampling.
     */
    fun toNv21(
        width: Int,
        height: Int,
        yBuffer: ByteBuffer,
        yRowStride: Int,
        yPixelStride: Int,
        uBuffer: ByteBuffer,
        uRowStride: Int,
        uPixelStride: Int,
        vBuffer: ByteBuffer,
        vRowStride: Int,
        vPixelStride: Int,
    ): ByteArray {
        require(width > 0 && height > 0) { "bad size ${width}x$height" }

        val ySize = width * height
        // NV21 is 12 bits per pixel: Y at full resolution plus one
        // half-resolution interleaved chroma plane.
        val nv21 = ByteArray(ySize + ySize / 2)
        var out = 0

        // ---- luma -----------------------------------------------------
        if (yPixelStride == 1 && yRowStride == width) {
            // Fast path: genuinely packed, so a single bulk copy is correct.
            yBuffer.position(0)
            yBuffer.get(nv21, 0, ySize)
            out = ySize
        } else {
            val row = ByteArray(yRowStride)
            for (r in 0 until height) {
                yBuffer.position(r * yRowStride)
                yBuffer.get(row, 0, minOf(yRowStride, yBuffer.remaining()))
                var i = 0
                var c = 0
                while (c < width) {
                    nv21[out++] = row[i]
                    i += yPixelStride
                    c++
                }
            }
        }

        // ---- chroma, interleaved V then U at half resolution -----------
        val chromaWidth = width / 2
        val chromaHeight = height / 2
        val uRow = ByteArray(uRowStride)
        val vRow = ByteArray(vRowStride)

        for (r in 0 until chromaHeight) {
            uBuffer.position(r * uRowStride)
            uBuffer.get(uRow, 0, minOf(uRowStride, uBuffer.remaining()))
            vBuffer.position(r * vRowStride)
            vBuffer.get(vRow, 0, minOf(vRowStride, vBuffer.remaining()))

            var ui = 0
            var vi = 0
            var c = 0
            while (c < chromaWidth) {
                nv21[out++] = vRow[vi]   // NV21 orders chroma V first
                nv21[out++] = uRow[ui]
                ui += uPixelStride
                vi += vPixelStride
                c++
            }
        }

        return nv21
    }
}
