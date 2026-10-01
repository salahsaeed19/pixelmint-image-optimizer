import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image


def noisy_image(size=(240, 160), mode="RGB"):
    """Deterministic-size image full of random pixels (compresses poorly, so
    quality changes have a clearly measurable effect)."""
    channels = len(Image.new(mode, (1, 1)).getbands())
    return Image.frombytes(mode, size, os.urandom(size[0] * size[1] * channels))


def image_bytes(img, fmt, **save_kwargs):
    buffer = io.BytesIO()
    img.save(buffer, fmt, **save_kwargs)
    return buffer.getvalue()


def make_upload(name="photo.jpg", fmt="JPEG", size=(240, 160), mode="RGB", **save_kwargs):
    data = image_bytes(noisy_image(size, mode), fmt, **save_kwargs)
    return SimpleUploadedFile(name, data, content_type=f"image/{fmt.lower()}")


def open_bytes(data):
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


class MediaTestCase(TestCase):
    """Runs every test against a throw-away MEDIA_ROOT that is always removed."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="optimizer-tests-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
