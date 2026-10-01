from django.test import SimpleTestCase, override_settings
from PIL import Image

from optimizer.services.image_processing import (
    ImageValidationError,
    ProcessingOptions,
    calculate_target_size,
    check_extension,
    optimize_image,
)
from optimizer.services.naming import display_filename, download_filename

from .helpers import image_bytes, noisy_image, open_bytes


class CalculateTargetSizeTests(SimpleTestCase):
    def test_no_resize_requested(self):
        self.assertEqual(calculate_target_size(800, 600, None, None), (800, 600))

    def test_width_only_preserves_aspect_ratio(self):
        self.assertEqual(calculate_target_size(800, 600, 400, None), (400, 300))

    def test_height_only_preserves_aspect_ratio(self):
        self.assertEqual(calculate_target_size(800, 600, None, 150), (200, 150))

    def test_both_fit_inside_box(self):
        # Width is the binding side.
        self.assertEqual(calculate_target_size(800, 600, 400, 400), (400, 300))
        # Height is the binding side.
        self.assertEqual(calculate_target_size(800, 600, 700, 150), (200, 150))

    def test_never_enlarges(self):
        self.assertEqual(calculate_target_size(800, 600, 2000, None), (800, 600))
        self.assertEqual(calculate_target_size(800, 600, 2000, 2000, False), (800, 600))

    def test_exact_size_without_aspect_ratio(self):
        self.assertEqual(calculate_target_size(800, 600, 400, 100, False), (400, 100))

    def test_single_side_without_aspect_ratio_keeps_other_side(self):
        self.assertEqual(calculate_target_size(800, 600, 400, None, False), (400, 600))

    def test_extreme_ratio_never_reaches_zero(self):
        width, height = calculate_target_size(4000, 10, 100, None)
        self.assertEqual(width, 100)
        self.assertGreaterEqual(height, 1)


class FormatAndQualityTests(SimpleTestCase):
    def test_jpeg_quality_changes_size(self):
        data = image_bytes(noisy_image(), "JPEG", quality=95)
        low = optimize_image(data, ProcessingOptions(quality=10))
        high = optimize_image(data, ProcessingOptions(quality=95))
        self.assertEqual(low.format, "JPEG")
        self.assertLess(len(low.data), len(high.data))
        self.assertEqual(open_bytes(low.data).format, "JPEG")

    def test_webp_quality_changes_size(self):
        data = image_bytes(noisy_image(), "WEBP", quality=95)
        low = optimize_image(data, ProcessingOptions(quality=10))
        high = optimize_image(data, ProcessingOptions(quality=95))
        self.assertEqual(low.format, "WEBP")
        self.assertLess(len(low.data), len(high.data))
        self.assertEqual(open_bytes(low.data).format, "WEBP")

    def test_png_is_lossless_and_unaffected_by_quality(self):
        source = noisy_image((60, 40))
        data = image_bytes(source, "PNG")
        a = optimize_image(data, ProcessingOptions(quality=10))
        b = optimize_image(data, ProcessingOptions(quality=100))
        self.assertEqual(a.format, "PNG")
        self.assertEqual(a.data, b.data)
        self.assertEqual(open_bytes(a.data).tobytes(), source.tobytes())

    def test_png_optimization_does_not_grow_a_flat_image(self):
        flat = Image.new("RGB", (300, 300), (10, 120, 200))
        data = image_bytes(flat, "PNG", compress_level=0)
        result = optimize_image(data, ProcessingOptions())
        self.assertLess(len(result.data), len(data))

    def test_convert_between_all_formats(self):
        for source_format in ("JPEG", "PNG", "WEBP"):
            data = image_bytes(noisy_image((64, 48)), source_format)
            for target in ("JPEG", "PNG", "WEBP"):
                with self.subTest(source=source_format, target=target):
                    result = optimize_image(data, ProcessingOptions(output_format=target))
                    self.assertEqual(result.format, target)
                    self.assertEqual(result.original_format, source_format)
                    self.assertEqual(open_bytes(result.data).format, target)

    def test_keep_original_format(self):
        for fmt in ("JPEG", "PNG", "WEBP"):
            data = image_bytes(noisy_image((32, 32)), fmt)
            self.assertEqual(optimize_image(data, ProcessingOptions()).format, fmt)

    def test_reports_original_and_optimized_metadata(self):
        data = image_bytes(noisy_image((200, 100)), "JPEG")
        result = optimize_image(data, ProcessingOptions(width=100))
        self.assertEqual(result.original_size, len(data))
        self.assertEqual((result.original_width, result.original_height), (200, 100))
        self.assertEqual((result.width, result.height), (100, 50))
        self.assertEqual(open_bytes(result.data).size, (100, 50))


class ResizeTests(SimpleTestCase):
    def test_resize_by_width_keeps_aspect_ratio(self):
        data = image_bytes(noisy_image((400, 300)), "JPEG")
        result = optimize_image(data, ProcessingOptions(width=200))
        self.assertEqual((result.width, result.height), (200, 150))

    def test_resize_exact_without_aspect_ratio(self):
        data = image_bytes(noisy_image((400, 300)), "PNG")
        result = optimize_image(
            data, ProcessingOptions(width=100, height=100, preserve_aspect_ratio=False)
        )
        self.assertEqual(open_bytes(result.data).size, (100, 100))

    def test_palette_png_is_resized_with_smooth_resampling(self):
        palette = noisy_image((80, 80)).quantize(colors=64)
        data = image_bytes(palette, "PNG")
        result = optimize_image(data, ProcessingOptions(width=40))
        self.assertEqual((result.width, result.height), (40, 40))


class ColorModeTests(SimpleTestCase):
    def test_transparent_png_to_jpeg_uses_white_background(self):
        rgba = Image.new("RGBA", (40, 40), (255, 0, 0, 0))  # fully transparent red
        data = image_bytes(rgba, "PNG")
        result = optimize_image(data, ProcessingOptions(output_format="JPEG", quality=100))
        out = open_bytes(result.data)
        self.assertEqual(out.mode, "RGB")
        r, g, b = out.getpixel((20, 20))
        self.assertGreater(min(r, g, b), 245)  # white, not black or red

    def test_semi_transparent_blends_onto_white(self):
        rgba = Image.new("RGBA", (40, 40), (0, 0, 0, 128))
        result = optimize_image(
            image_bytes(rgba, "PNG"), ProcessingOptions(output_format="JPEG", quality=100)
        )
        r, g, b = open_bytes(result.data).getpixel((20, 20))
        self.assertTrue(110 <= r <= 145 and 110 <= g <= 145 and 110 <= b <= 145)

    def test_palette_transparency_to_jpeg_uses_white_background(self):
        base = Image.new("RGBA", (40, 40), (0, 0, 255, 0))
        palette = base.convert("P")
        data = image_bytes(palette, "PNG", transparency=0)
        result = optimize_image(data, ProcessingOptions(output_format="JPEG", quality=100))
        r, g, b = open_bytes(result.data).getpixel((20, 20))
        self.assertGreater(min(r, g, b), 245)

    def test_png_keeps_alpha(self):
        rgba = Image.new("RGBA", (30, 30), (10, 20, 30, 100))
        result = optimize_image(image_bytes(rgba, "PNG"), ProcessingOptions())
        out = open_bytes(result.data)
        self.assertEqual(out.mode, "RGBA")
        self.assertEqual(out.getpixel((5, 5))[3], 100)

    def test_png_to_webp_keeps_alpha(self):
        rgba = Image.new("RGBA", (30, 30), (10, 20, 30, 0))
        result = optimize_image(
            image_bytes(rgba, "PNG"), ProcessingOptions(output_format="WEBP", quality=100)
        )
        out = open_bytes(result.data)
        self.assertIn("A", out.getbands())
        self.assertEqual(out.convert("RGBA").getpixel((5, 5))[3], 0)

    def test_grayscale_png_to_each_format(self):
        gray = noisy_image((30, 30), "L")
        data = image_bytes(gray, "PNG")
        for target in ("JPEG", "PNG", "WEBP"):
            with self.subTest(target=target):
                result = optimize_image(data, ProcessingOptions(output_format=target))
                self.assertEqual(result.format, target)

    def test_cmyk_jpeg_is_converted_to_rgb_png(self):
        cmyk = Image.new("CMYK", (30, 30), (0, 255, 255, 0))
        data = image_bytes(cmyk, "JPEG")
        result = optimize_image(data, ProcessingOptions(output_format="PNG"))
        self.assertEqual(open_bytes(result.data).mode, "RGB")

    def test_16_bit_grayscale_png(self):
        img = Image.new("I;16", (20, 20), 40000)
        data = image_bytes(img, "PNG")
        result = optimize_image(data, ProcessingOptions(output_format="JPEG"))
        self.assertEqual(result.format, "JPEG")


class ExifOrientationTests(SimpleTestCase):
    def _jpeg_with_orientation(self, orientation):
        img = noisy_image((80, 40))
        exif = Image.Exif()
        exif[0x0112] = orientation
        return image_bytes(img, "JPEG", exif=exif)

    def test_rotated_image_is_made_upright(self):
        data = self._jpeg_with_orientation(6)  # stored 80x40, displayed 40x80
        result = optimize_image(data, ProcessingOptions())
        self.assertEqual((result.original_width, result.original_height), (40, 80))
        self.assertEqual(open_bytes(result.data).size, (40, 80))

    def test_orientation_is_applied_before_resize(self):
        data = self._jpeg_with_orientation(8)
        result = optimize_image(data, ProcessingOptions(height=20))
        self.assertEqual((result.width, result.height), (10, 20))

    def test_exif_is_not_written_back(self):
        result = optimize_image(self._jpeg_with_orientation(6), ProcessingOptions())
        self.assertNotIn(0x0112, open_bytes(result.data).getexif())


class ValidationTests(SimpleTestCase):
    def test_random_bytes_are_rejected(self):
        with self.assertRaises(ImageValidationError):
            optimize_image(b"definitely not an image" * 20, ProcessingOptions())

    def test_empty_file_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            optimize_image(b"", ProcessingOptions())

    def test_truncated_image_is_rejected(self):
        data = image_bytes(noisy_image((200, 200)), "PNG")
        with self.assertRaises(ImageValidationError):
            optimize_image(data[: len(data) // 2], ProcessingOptions())

    def test_truncated_jpeg_is_rejected(self):
        data = image_bytes(noisy_image((200, 200)), "JPEG")
        with self.assertRaises(ImageValidationError):
            optimize_image(data[: len(data) // 2], ProcessingOptions())

    def test_valid_image_in_unsupported_format_is_rejected(self):
        gif = image_bytes(Image.new("P", (20, 20)), "GIF")
        with self.assertRaises(ImageValidationError):
            optimize_image(gif, ProcessingOptions())

    def test_bmp_content_is_rejected(self):
        bmp = image_bytes(noisy_image((20, 20)), "BMP")
        with self.assertRaises(ImageValidationError):
            optimize_image(bmp, ProcessingOptions())

    def test_extension_is_not_trusted(self):
        # check_extension only gates by name; the content check is separate.
        check_extension("fake.png")
        with self.assertRaises(ImageValidationError):
            optimize_image(b"<?php echo 1; ?>", ProcessingOptions())

    def test_real_format_wins_over_extension(self):
        png_data = image_bytes(noisy_image((20, 20)), "PNG")
        result = optimize_image(png_data, ProcessingOptions())  # imagine "x.jpg"
        self.assertEqual(result.original_format, "PNG")
        self.assertEqual(result.format, "PNG")

    def test_unsupported_extensions_are_rejected(self):
        for name in ("a.gif", "a.txt", "a.svg", "a.bmp", "a", "a.jpg.exe", "a.tiff"):
            with self.subTest(name=name), self.assertRaises(ImageValidationError):
                check_extension(name)

    def test_supported_extensions_are_accepted(self):
        for name in ("a.jpg", "a.JPEG", "a.png", "a.WebP", "dir\\a.png"):
            check_extension(name)

    @override_settings(OPTIMIZER_MAX_FILE_SIZE=1000)
    def test_oversized_data_is_rejected(self):
        data = image_bytes(noisy_image((100, 100)), "PNG")
        with self.assertRaises(ImageValidationError):
            optimize_image(data, ProcessingOptions())

    @override_settings(OPTIMIZER_MAX_PIXELS=100)
    def test_pixel_limit(self):
        data = image_bytes(noisy_image((50, 50)), "PNG")
        with self.assertRaises(ImageValidationError):
            optimize_image(data, ProcessingOptions())

    def test_quality_out_of_range_is_rejected(self):
        data = image_bytes(noisy_image((20, 20)), "JPEG")
        for quality in (0, 9, 101):
            with self.subTest(quality=quality), self.assertRaises(ImageValidationError):
                optimize_image(data, ProcessingOptions(quality=quality))


class NamingTests(SimpleTestCase):
    def test_display_filename_strips_paths(self):
        self.assertEqual(display_filename("../../etc/passwd.png"), "passwd.png")
        self.assertEqual(display_filename("C:\\Users\\me\\pic.jpg"), "pic.jpg")

    def test_display_filename_removes_control_characters(self):
        self.assertEqual(display_filename("a\x00b\nc.png"), "abc.png")

    def test_display_filename_fallback_and_length(self):
        self.assertEqual(display_filename(""), "image")
        self.assertLessEqual(len(display_filename("x" * 400 + ".png")), 255)
        self.assertTrue(display_filename("x" * 400 + ".png").endswith(".png"))

    def test_download_filename(self):
        self.assertEqual(download_filename("My Photo.JPEG", "webp"), "My_Photo-optimized.webp")
        self.assertEqual(download_filename("../..", "png"), "image-optimized.png")
