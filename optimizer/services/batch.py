"""Orchestrates optimizing a batch of uploads and recording history."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from ..models import OptimizationRecord
from .image_processing import (
    FORMAT_EXTENSIONS,
    ImageValidationError,
    ProcessingOptions,
    check_extension,
    optimize_image,
)
from .naming import display_filename, storage_name

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    batch_id: uuid.UUID
    records: list[OptimizationRecord] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (filename, message)
    warnings: list[str] = field(default_factory=list)


def _save_record(batch_id, filename, original_data, result, options) -> OptimizationRecord:
    record_id = uuid.uuid4()
    original_ext = FORMAT_EXTENSIONS[result.original_format]
    output_ext = FORMAT_EXTENSIONS[result.format]
    reduction = (
        (result.original_size - len(result.data)) / result.original_size * 100
        if result.original_size
        else 0.0
    )
    record = OptimizationRecord(
        id=record_id,
        batch_id=batch_id,
        original_filename=filename,
        original_format=result.original_format,
        output_format=result.format,
        original_width=result.original_width,
        original_height=result.original_height,
        output_width=result.width,
        output_height=result.height,
        original_size=result.original_size,
        optimized_size=len(result.data),
        quality=options.quality,
        reduction_percent=round(reduction, 2),
    )
    original_name = storage_name(original_ext)
    optimized_name = storage_name(output_ext)
    # Fresh UUID names: nothing existing can ever be overwritten.
    record.original_file.save(original_name, ContentFile(original_data), save=False)
    try:
        record.optimized_file.save(
            optimized_name, ContentFile(result.data), save=False
        )
        with transaction.atomic():
            record.save(force_insert=True)
    except Exception:
        # Do not leave orphaned files behind if saving fails midway.
        for stored in (record.original_file, record.optimized_file):
            if stored and stored.name:
                stored.storage.delete(stored.name)
        raise
    return record


def process_batch(uploads, options: ProcessingOptions) -> BatchResult:
    """Optimize every upload. One bad file never blocks the others."""
    result = BatchResult(batch_id=uuid.uuid4())
    for upload in uploads:
        filename = display_filename(upload.name)
        try:
            check_extension(filename)
            # Check size before reading the file into memory.
            if upload.size > settings.OPTIMIZER_MAX_FILE_SIZE:
                limit = settings.OPTIMIZER_MAX_FILE_SIZE / (1024 * 1024)
                raise ImageValidationError(
                    f"The file is larger than the {limit:g} MB limit."
                )
            data = upload.read()
            optimized = optimize_image(data, options)
            record = _save_record(result.batch_id, filename, data, optimized, options)
        except ImageValidationError as exc:
            result.errors.append((filename, str(exc)))
            continue
        except Exception:  # unexpected: log it, show a friendly message
            logger.exception("Unexpected failure while optimizing %r", filename)
            result.errors.append(
                (filename, "Something went wrong while processing this image.")
            )
            continue
        result.records.append(record)
        if optimized.animated:
            result.warnings.append(
                f"{filename}: animation is not preserved; only the first frame was used."
            )
    return result

