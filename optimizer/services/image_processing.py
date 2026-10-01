"""Pure Pillow image processing. Knows nothing about Django requests or models."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePath

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

# Pillow format name -> file extension
FORMAT_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
ALLOWED_INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Form value -> Pillow format name (None = keep the original format)
OUTPUT_FORMAT_CHOICES = {
    "original": None,
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}

MIN_QUALITY = 10
MAX_QUALITY = 100


class ImageValidationError(Exception):
    """Raised for expected, user-facing problems with an uploaded image."""


@dataclass(frozen=True)
class ProcessingOptions:
    quality: int = 80
    width: int | None = None
    height: int | None = None
    preserve_aspect_ratio: bool = True
    output_format: str | None = None  # Pillow name, or None to keep original


@dataclass(frozen=True)
class OptimizedImage:
    data: bytes
    format: str
    width: int
    height: int
    original_format: str
    original_width: int
    original_height: int
    original_size: int
    animated: bool = False


def _human_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):g} MB"


def check_extension(filename: str) -> None:
    suffix = PurePath(filename.replace("\\", "/")).suffix.lower()
    if suffix not in ALLOWED_INPUT_EXTENSIONS:
        raise ImageValidationError(
            "Unsupported file type. Please upload JPG, PNG or WebP images."
        )


def _probe(data: bytes) -> tuple[str, int, int]:
    """Cheaply confirm the bytes are a real, supported, reasonably sized image."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in FORMAT_EXTENSIONS:
                raise ImageValidationError(
                    "Unsupported image content. Please upload JPG, PNG or WebP images."
                )
            if width * height > settings.OPTIMIZER_MAX_PIXELS:
                raise ImageValidationError(
                    "This image has too many pixels to process safely."
                )
            probe.verify()
            return fmt, width, height
    except ImageValidationError:
        raise
    except Image.DecompressionBombError:
        raise ImageValidationError("This image has too many pixels to process safely.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise ImageValidationError(
            "This file is not a valid image or appears to be corrupted."
        )


def calculate_target_size(
    original_width: int,
    original_height: int,
    width: int | None,
    height: int | None,
    preserve_aspect_ratio: bool = True,
) -> tuple[int, int]:
    """Return the output size. Images are never enlarged.

    * No width/height -> unchanged.
    * preserve_aspect_ratio -> fit inside the requested box (width and/or height).
    * otherwise -> use the requested width/height exactly (a missing one keeps the
      original value), capped at the original dimensions.
    """
    if not width and not height:
        return original_width, original_height

    if preserve_aspect_ratio:
        scales = []
        if width:
            scales.append(width / original_width)
        if height:
            scales.append(height / original_height)
        scale = min(scales)
        if scale >= 1:
            return original_width, original_height
        return (
            max(1, round(original_width * scale)),
            max(1, round(original_height * scale)),
        )

    return (
        max(1, min(width or original_width, original_width)),
        max(1, min(height or original_height, original_height)),
    )


def _to_working_mode(img: Image.Image) -> Image.Image:
    """Convert to L / RGB / RGBA, which all resample and encode reliably."""
    mode = img.mode
    has_transparency = "transparency" in img.info

    if mode in ("I;16", "I;16L", "I;16B", "I;16N", "I"):
        return img.point(lambda value: value * (1 / 256)).convert("L")
    if mode in ("RGBA", "RGB") or (mode == "L" and not has_transparency):
        return img.copy()
    if mode in ("P", "L", "1") and has_transparency:
        return img.convert("RGBA")
    if mode in ("LA", "PA", "La", "RGBa"):
        return img.convert("RGBA")
    if mode == "P":
        # Palette images may carry an RGBA palette.
        return img.convert("RGBA" if img.palette and img.palette.mode == "RGBA" else "RGB")
    if mode == "1":
        return img.convert("L")
    return img.convert("RGB")  # CMYK, YCbCr, LAB, HSV, ...


def _prepare_for_format(img: Image.Image, target_format: str) -> Image.Image:
    if target_format == "JPEG":
        if img.mode == "RGBA":
            # JPEG has no alpha channel: composite onto white, not black.
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.getchannel("A"))
            return background
        return img  # L or RGB
    if target_format == "WEBP" and img.mode == "L":
        return img.convert("RGB")
    return img  # PNG accepts L / RGB / RGBA; WebP accepts RGB / RGBA


def _encode(img: Image.Image, target_format: str, quality: int, icc_profile) -> bytes:
    buffer = io.BytesIO()
    extra = {"icc_profile": icc_profile} if icc_profile else {}
    if target_format == "JPEG":
        img.save(
            buffer, "JPEG", quality=quality, optimize=True, progressive=True, **extra
        )
    elif target_format == "WEBP":
        img.save(buffer, "WEBP", quality=quality, method=6, **extra)
    else:  # PNG is lossless: quality does not apply, so squeeze with max deflate.
        img.save(buffer, "PNG", optimize=True, compress_level=9, **extra)
    return buffer.getvalue()


def optimize_image(data: bytes, options: ProcessingOptions) -> OptimizedImage:
    """Validate ``data`` with Pillow, then resize / convert / compress it."""
    if not data:
        raise ImageValidationError("The file is empty.")
    if len(data) > settings.OPTIMIZER_MAX_FILE_SIZE:
        raise ImageValidationError(
            f"The file is larger than the {_human_mb(settings.OPTIMIZER_MAX_FILE_SIZE)} limit."
        )
    if not MIN_QUALITY <= options.quality <= MAX_QUALITY:
        raise ImageValidationError(
            f"Quality must be between {MIN_QUALITY} and {MAX_QUALITY}."
        )

    source_format, _, _ = _probe(data)
    target_format = options.output_format or source_format

    opened: list[Image.Image] = []
    try:
        src = Image.open(io.BytesIO(data))
        opened.append(src)
        src.load()  # full decode: truncated/corrupt pixel data fails here
        animated = bool(getattr(src, "is_animated", False))
        icc_profile = src.info.get("icc_profile")
        if src.mode in ("CMYK", "YCbCr", "LAB", "HSV"):
            icc_profile = None  # profile no longer matches the converted pixels

        # Apply EXIF orientation so pixels are upright; EXIF is not written back.
        oriented = ImageOps.exif_transpose(src)
        opened.append(oriented)
        original_width, original_height = oriented.size

        working = _to_working_mode(oriented)
        opened.append(working)

        new_size = calculate_target_size(
            original_width,
            original_height,
            options.width,
            options.height,
            options.preserve_aspect_ratio,
        )
        if new_size != working.size:
            working = working.resize(new_size, Image.Resampling.LANCZOS)
            opened.append(working)

        final = _prepare_for_format(working, target_format)
        if final is not working:
            opened.append(final)

        encoded = _encode(final, target_format, options.quality, icc_profile)
        return OptimizedImage(
            data=encoded,
            format=target_format,
            width=final.width,
            height=final.height,
            original_format=source_format,
            original_width=original_width,
            original_height=original_height,
            original_size=len(data),
            animated=animated,
        )
    except ImageValidationError:
        raise
    except Image.DecompressionBombError:
        raise ImageValidationError("This image has too many pixels to process safely.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise ImageValidationError(
            "This file is not a valid image or appears to be corrupted."
        )
    finally:
        for image in opened:
            image.close()
