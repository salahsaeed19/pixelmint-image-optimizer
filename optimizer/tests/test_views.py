import io
import zipfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from optimizer.models import OptimizationRecord

from .helpers import MediaTestCase, image_bytes, make_upload, noisy_image, open_bytes


def post_images(client, uploads, **fields):
    data = {"quality": "80", "output_format": "original", "preserve_aspect_ratio": "on"}
    data.update(fields)
    data["images"] = uploads
    return client.post(reverse("optimizer:home"), data)


class PageTests(MediaTestCase):
    def test_home_page(self):
        response = self.client.get(reverse("optimizer:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Drop your images here")
        self.assertContains(response, "click to browse")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, 'value="80"')  # default quality
        self.assertContains(response, "Built with Django &amp; Pillow")
        self.assertContains(response, ">Home<")
        self.assertContains(response, ">How it works<")
        self.assertContains(response, ">History<")
        self.assertContains(response, "Clean images.")
        self.assertContains(response, "See the difference")
        for step in ("Upload", "Optimize", "Download"):
            self.assertContains(response, f"<h3>{step}</h3>")

    def test_brand_is_pixelmint_everywhere(self):
        for name in ("home", "history"):
            response = self.client.get(reverse(f"optimizer:{name}"))
            self.assertContains(response, "<title>")
            self.assertContains(response, "PixelMint")
            self.assertNotContains(response, "Image Optimizer")

    def test_output_format_choices_are_rendered(self):
        response = self.client.get(reverse("optimizer:home"))
        for value in ("original", "jpg", "png", "webp"):
            self.assertContains(response, f'name="output_format" value="{value}"')
        self.assertContains(response, 'value="original" checked')

    def test_every_referenced_static_asset_exists(self):
        import re

        from django.contrib.staticfiles import finders

        paths = set()
        for name in ("home", "history"):
            html = self.client.get(reverse(f"optimizer:{name}")).content.decode()
            paths.update(re.findall(r'/static/([^"\']+)', html))
        self.assertTrue({"optimizer/css/base.css", "optimizer/js/app.js"} <= paths)
        for path in paths:
            self.assertIsNotNone(finders.find(path), path)
        # Files only referenced from CSS.
        self.assertIsNotNone(finders.find("optimizer/fonts/manrope-latin-wght-normal.woff2"))
        self.assertIsNotNone(finders.find("optimizer/fonts/manrope-latin-ext-wght-normal.woff2"))

    def test_empty_history_page(self):
        response = self.client.get(reverse("optimizer:history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No history yet")

    def test_unknown_urls_give_friendly_404(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/nope/")
            self.assertEqual(response.status_code, 404)
            self.assertContains(response, "Page not found", status_code=404)
            missing = reverse("optimizer:download", args=["00000000-0000-0000-0000-000000000000"])
            self.assertEqual(self.client.get(missing).status_code, 404)


class SourceEncodingTests(MediaTestCase):
    def test_templates_and_static_files_are_clean_utf8(self):
        """Guards against mojibake (e.g. 'â€¦') and stray BOMs in front-end files."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        mojibake = ("\u00e2\u20ac", "\u00c2\u00b7", "\u00c3\u2014")
        checked = 0
        for folder in ("templates", "static"):
            for path in (root / folder).rglob("*"):
                if path.suffix not in {".html", ".css", ".js"}:
                    continue
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM in {path.name}")
                text = raw.decode("utf-8")
                for bad in mojibake:
                    self.assertNotIn(bad, text, f"mojibake in {path.name}")
                checked += 1
        self.assertGreaterEqual(checked, 8)


class OptimizeFlowTests(MediaTestCase):
    def test_single_jpeg_end_to_end(self):
        upload = make_upload("holiday.jpg", "JPEG", (400, 300), quality=95)
        original_bytes = upload.read()
        upload.seek(0)

        response = post_images(self.client, [upload], quality="40", width="200")
        self.assertEqual(response.status_code, 302)

        record = OptimizationRecord.objects.get()
        self.assertEqual(record.original_filename, "holiday.jpg")
        self.assertEqual((record.original_format, record.output_format), ("JPEG", "JPEG"))
        self.assertEqual((record.original_width, record.original_height), (400, 300))
        self.assertEqual((record.output_width, record.output_height), (200, 150))
        self.assertEqual(record.quality, 40)
        self.assertEqual(record.original_size, len(original_bytes))
        self.assertLess(record.optimized_size, record.original_size)
        self.assertGreater(record.reduction_percent, 0)
        self.assertAlmostEqual(
            record.reduction_percent,
            (record.original_size - record.optimized_size) / record.original_size * 100,
            places=1,
        )
        self.assertIn(str(record.batch_id), response.url)

        # Files are stored under server-generated names, never the client's.
        self.assertRegex(record.original_file.name, r"^originals/[0-9a-f]{32}\.jpg$")
        self.assertRegex(record.optimized_file.name, r"^optimized/[0-9a-f]{32}\.jpg$")
        with record.original_file.open("rb") as handle:
            self.assertEqual(handle.read(), original_bytes)  # original untouched
        with record.optimized_file.open("rb") as handle:
            self.assertEqual(open_bytes(handle.read()).size, (200, 150))
            self.assertEqual(record.optimized_size, record.optimized_file.size)

        results = self.client.get(response.url)
        self.assertContains(results, "holiday.jpg")
        self.assertContains(results, "400 × 300 px")
        self.assertContains(results, "200 × 150 px")
        self.assertContains(results, "Saved")
        self.assertContains(results, record.optimized_file.url)
        self.assertNotContains(results, "Download all")  # single image

    def test_png_processing(self):
        upload = make_upload("graphic.png", "PNG", (120, 80), mode="RGBA")
        post_images(self.client, [upload])
        record = OptimizationRecord.objects.get()
        self.assertEqual(record.output_format, "PNG")
        with record.optimized_file.open("rb") as handle:
            self.assertEqual(open_bytes(handle.read()).mode, "RGBA")

    def test_webp_processing_and_quality(self):
        upload = make_upload("pic.webp", "WEBP", (200, 150), quality=95)
        post_images(self.client, [upload], quality="20")
        record = OptimizationRecord.objects.get()
        self.assertEqual(record.output_format, "WEBP")
        self.assertEqual(record.quality, 20)
        self.assertLess(record.optimized_size, record.original_size)

    def test_format_conversion_png_to_jpg_flattens_transparency(self):
        rgba = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        upload = SimpleUploadedFile("logo.png", image_bytes(rgba, "PNG"))
        post_images(self.client, [upload], output_format="jpg", quality="100")
        record = OptimizationRecord.objects.get()
        self.assertEqual((record.original_format, record.output_format), ("PNG", "JPEG"))
        self.assertRegex(record.optimized_file.name, r"\.jpg$")
        with record.optimized_file.open("rb") as handle:
            out = open_bytes(handle.read())
        self.assertGreater(min(out.getpixel((25, 25))), 245)

    def test_resize_preserving_and_not_preserving_aspect_ratio(self):
        post_images(self.client, [make_upload("a.png", "PNG", (400, 200))], height="50")
        a = OptimizationRecord.objects.get(original_filename="a.png")
        self.assertEqual((a.output_width, a.output_height), (100, 50))

        # Unchecked checkbox is simply absent from the POST data.
        data = {
            "quality": "80",
            "output_format": "original",
            "width": "80",
            "height": "80",
            "images": [make_upload("b.png", "PNG", (400, 200))],
        }
        self.client.post(reverse("optimizer:home"), data)
        b = OptimizationRecord.objects.get(original_filename="b.png")
        self.assertEqual((b.output_width, b.output_height), (80, 80))

    def test_output_larger_than_source_is_reported_honestly(self):
        tiny = Image.new("RGB", (64, 64), (200, 30, 30))
        upload = SimpleUploadedFile("flat.png", image_bytes(tiny, "PNG", optimize=True))
        response = post_images(self.client, [upload], output_format="jpg", quality="100")
        record = OptimizationRecord.objects.get()
        self.assertTrue(record.is_larger)
        self.assertLess(record.reduction_percent, 0)
        self.assertGreater(record.optimized_size, record.original_size)
        results = self.client.get(response.url)
        self.assertContains(results, "larger")
        self.assertNotContains(results, "Saved <strong>")
        history = self.client.get(reverse("optimizer:history"))
        self.assertContains(history, "larger")

    def test_default_quality_is_80_in_form_and_view(self):
        self.assertContains(self.client.get(reverse("optimizer:home")), 'value="80"')

    def test_multiple_images_and_zip(self):
        uploads = [
            make_upload("one.jpg", "JPEG"),
            make_upload("two.png", "PNG"),
            make_upload("three.webp", "WEBP"),
        ]
        response = post_images(self.client, uploads)
        self.assertEqual(OptimizationRecord.objects.count(), 3)
        self.assertEqual(len({r.batch_id for r in OptimizationRecord.objects.all()}), 1)

        results = self.client.get(response.url)
        self.assertContains(results, "Download all (ZIP)")

        batch_id = OptimizationRecord.objects.first().batch_id
        zip_response = self.client.get(reverse("optimizer:download_zip", args=[batch_id]))
        self.assertEqual(zip_response.status_code, 200)
        self.assertEqual(zip_response["Content-Type"], "application/zip")
        self.assertIn("attachment", zip_response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(
                sorted(archive.namelist()),
                ["one-optimized.jpg", "three-optimized.webp", "two-optimized.png"],
            )
            for name in archive.namelist():
                Image.open(io.BytesIO(archive.read(name))).verify()

    def test_zip_handles_duplicate_filenames(self):
        uploads = [make_upload("same.jpg"), make_upload("same.jpg")]
        post_images(self.client, uploads)
        batch_id = OptimizationRecord.objects.first().batch_id
        response = self.client.get(reverse("optimizer:download_zip", args=[batch_id]))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(len(set(archive.namelist())), 2)

    def test_individual_download(self):
        post_images(self.client, [make_upload("My Photo.png", "PNG", (50, 50))])
        record = OptimizationRecord.objects.get()
        response = self.client.get(reverse("optimizer:download", args=[record.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("My_Photo-optimized.png", response["Content-Disposition"])
        self.assertEqual(response["Content-Type"], "image/png")
        body = b"".join(response.streaming_content)
        self.assertEqual(len(body), record.optimized_size)
        self.assertEqual(Image.open(io.BytesIO(body)).format, "PNG")

    def test_download_for_missing_file_is_404_not_a_crash(self):
        post_images(self.client, [make_upload("x.jpg")])
        record = OptimizationRecord.objects.get()
        record.optimized_file.storage.delete(record.optimized_file.name)
        with override_settings(DEBUG=False):
            self.assertEqual(
                self.client.get(reverse("optimizer:download", args=[record.pk])).status_code, 404
            )

    def test_hostile_filename_is_never_used_on_disk(self):
        upload = SimpleUploadedFile(
            "../../evil<script>.png", image_bytes(noisy_image((20, 20)), "PNG")
        )
        response = post_images(self.client, [upload])
        record = OptimizationRecord.objects.get()
        self.assertNotIn("evil", record.optimized_file.name)
        self.assertNotIn("evil", record.original_file.name)
        self.assertNotIn("..", record.original_filename)
        self.assertNotContains(self.client.get(response.url), "<script>")

    def test_uploading_the_same_file_twice_never_overwrites(self):
        data = image_bytes(noisy_image((30, 30)), "PNG")
        for _ in range(2):
            post_images(self.client, [SimpleUploadedFile("dup.png", data)])
        names = {r.original_file.name for r in OptimizationRecord.objects.all()}
        self.assertEqual(len(names), 2)


class ValidationFlowTests(MediaTestCase):
    def assertNoTraceback(self, response):
        content = response.content.decode()
        self.assertNotIn("Traceback", content)
        self.assertNotIn("Exception Value", content)

    def test_corrupted_image_is_rejected_cleanly(self):
        bad = SimpleUploadedFile("broken.jpg", b"\xff\xd8\xff\xe0" + b"garbage" * 50)
        response = post_images(self.client, [bad])
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "broken.jpg", status_code=400)
        self.assertContains(response, "not a valid image", status_code=400)
        self.assertNoTraceback(response)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_unsupported_file_type_is_rejected(self):
        txt = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        response = post_images(self.client, [txt])
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Unsupported file type", status_code=400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_gif_is_rejected_even_when_renamed_to_jpg(self):
        gif = SimpleUploadedFile("sneaky.jpg", image_bytes(Image.new("P", (10, 10)), "GIF"))
        response = post_images(self.client, [gif])
        self.assertContains(response, "Unsupported image content", status_code=400)

    def test_text_renamed_to_png_is_rejected(self):
        fake = SimpleUploadedFile("fake.png", b"just some text, not a png")
        response = post_images(self.client, [fake])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    @override_settings(OPTIMIZER_MAX_FILE_SIZE=2000)
    def test_file_over_size_limit_is_rejected(self):
        big = make_upload("big.png", "PNG", (100, 100))
        self.assertGreater(big.size, 2000)
        response = post_images(self.client, [big])
        self.assertContains(response, "larger than the", status_code=400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_file_over_15_mb_limit_is_rejected(self):
        # 15 MB + 1 byte of padding after a valid PNG: rejected on size alone.
        data = image_bytes(noisy_image((10, 10)), "PNG") + b"\0" * (15 * 1024 * 1024)
        response = post_images(self.client, [SimpleUploadedFile("huge.png", data)])
        self.assertContains(response, "15 MB limit", status_code=400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_exactly_ten_images_are_accepted(self):
        uploads = [make_upload(f"img{i}.jpg", size=(40, 40)) for i in range(10)]
        response = post_images(self.client, uploads)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(OptimizationRecord.objects.count(), 10)

    def test_more_than_ten_images_are_rejected(self):
        uploads = [make_upload(f"img{i}.jpg", size=(40, 40)) for i in range(11)]
        response = post_images(self.client, uploads)
        self.assertContains(response, "at most 10 images", status_code=400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_no_files(self):
        response = self.client.post(
            reverse("optimizer:home"), {"quality": "80", "output_format": "original"}
        )
        self.assertContains(response, "Choose at least one image", status_code=400)

    def test_invalid_settings(self):
        for field, value in (
            ("quality", "9"),
            ("quality", "101"),
            ("quality", "abc"),
            ("width", "0"),
            ("height", "-5"),
            ("width", "99999"),
            ("output_format", "gif"),
        ):
            with self.subTest(field=field, value=value):
                response = post_images(self.client, [make_upload()], **{field: value})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_quality_boundaries_are_accepted(self):
        for quality in ("10", "100"):
            response = post_images(self.client, [make_upload()], quality=quality)
            self.assertEqual(response.status_code, 302)

    def test_bad_file_does_not_block_good_ones(self):
        good = make_upload("good.jpg")
        bad = SimpleUploadedFile("bad.png", b"nope")
        response = post_images(self.client, [good, bad])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(OptimizationRecord.objects.count(), 1)
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("bad.png" in m for m in messages))
        self.assertContains(self.client.get(response.url), "bad.png")

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("optimizer:home"), {"images": [make_upload()], "quality": "80"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(OptimizationRecord.objects.count(), 0)

    def test_unexpected_processing_error_is_friendly(self):
        from unittest import mock

        with mock.patch(
            "optimizer.services.batch.optimize_image", side_effect=RuntimeError("boom")
        ), self.assertLogs("optimizer.services.batch", level="ERROR"):
            response = post_images(self.client, [make_upload("x.jpg")])
        self.assertContains(response, "Something went wrong", status_code=400)
        self.assertNotContains(response, "boom", status_code=400)
        self.assertNoTraceback(response)

    def test_animated_webp_warns_that_only_first_frame_is_used(self):
        frames = [Image.new("RGB", (30, 30), c) for c in ("red", "blue")]
        data = io.BytesIO()
        frames[0].save(data, "WEBP", save_all=True, append_images=frames[1:], duration=100)
        response = post_images(self.client, [SimpleUploadedFile("anim.webp", data.getvalue())])
        self.assertContains(self.client.get(response.url), "animation is not preserved")


class HistoryTests(MediaTestCase):
    def test_history_lists_records_newest_first(self):
        for name in ("first.jpg", "second.jpg", "third.jpg"):
            post_images(self.client, [make_upload(name)])
        # Make creation order unambiguous regardless of clock resolution.
        now = timezone.now()
        for offset, name in enumerate(("first.jpg", "second.jpg", "third.jpg")):
            OptimizationRecord.objects.filter(original_filename=name).update(
                created_at=now + timedelta(minutes=offset)
            )
        response = self.client.get(reverse("optimizer:history"))
        names = [r.original_filename for r in response.context["page"].object_list]
        self.assertEqual(names, ["third.jpg", "second.jpg", "first.jpg"])
        self.assertContains(response, "third.jpg")
        self.assertContains(response, "Download")

    def test_history_paginates(self):
        for i in range(14):
            post_images(self.client, [make_upload(f"p{i}.jpg", size=(20, 20))])
        response = self.client.get(reverse("optimizer:history"))
        self.assertEqual(len(response.context["page"].object_list), 12)
        self.assertContains(response, "Older")
        page2 = self.client.get(reverse("optimizer:history") + "?page=2")
        self.assertEqual(len(page2.context["page"].object_list), 2)
        self.assertEqual(self.client.get(reverse("optimizer:history") + "?page=junk").status_code, 200)

    def test_history_record_has_all_metadata_and_no_binary(self):
        post_images(self.client, [make_upload("meta.png", "PNG", (90, 60))], output_format="webp")
        record = OptimizationRecord.objects.get()
        for field in (
            "original_filename", "original_format", "output_format", "original_width",
            "original_height", "output_width", "output_height", "original_size",
            "optimized_size", "quality", "reduction_percent", "created_at",
        ):
            self.assertIsNotNone(getattr(record, field), field)
        self.assertEqual((record.original_format, record.output_format), ("PNG", "WEBP"))
        field_types = {f.name: f.get_internal_type() for f in OptimizationRecord._meta.fields}
        self.assertNotIn("BinaryField", field_types.values())

    def test_deleting_a_record_removes_its_files(self):
        post_images(self.client, [make_upload("gone.jpg")])
        record = OptimizationRecord.objects.get()
        storage = record.optimized_file.storage
        names = [record.original_file.name, record.optimized_file.name]
        record.delete()
        for name in names:
            self.assertFalse(storage.exists(name))


class AdminTests(MediaTestCase):
    def test_admin_changelist_and_change_pages(self):
        user = get_user_model().objects.create_superuser("admin", "a@example.com", "pw-12345!")
        self.client.force_login(user)
        post_images(self.client, [make_upload("admin.jpg")])
        record = OptimizationRecord.objects.get()

        changelist = self.client.get(reverse("admin:optimizer_optimizationrecord_changelist"))
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, "admin.jpg")

        change = self.client.get(
            reverse("admin:optimizer_optimizationrecord_change", args=[record.pk])
        )
        self.assertEqual(change.status_code, 200)
