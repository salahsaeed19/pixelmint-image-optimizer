"""Filename helpers. Uploaded names are only ever used for display/downloads."""

import re
import uuid
from pathlib import PurePath

from django.core.exceptions import SuspiciousFileOperation
from django.utils.text import get_valid_filename

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def display_filename(name: str) -> str:
    """A clean, bounded version of the client-supplied filename (no path parts)."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = _CONTROL_CHARS.sub("", base).strip()
    if len(base) > 255:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 250 - len(ext)] + dot + ext) if dot else base[:255]
    return base or "image"


def storage_name(extension: str) -> str:
    """Server-chosen name; the client filename never touches the filesystem.

    The folder (originals/ or optimized/) comes from the model field's upload_to.
    """
    return f"{uuid.uuid4().hex}.{extension}"


def download_filename(original_name: str, extension: str) -> str:
    stem = PurePath(display_filename(original_name)).stem
    try:
        stem = get_valid_filename(stem)[:100].strip("._") or "image"
    except SuspiciousFileOperation:
        stem = "image"
    return f"{stem}-optimized.{extension}"
