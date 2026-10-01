import uuid

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class OptimizationRecord(models.Model):
    """Metadata about one optimized image.

    Only file *paths* live in SQLite; the image bytes are stored in MEDIA_ROOT.
    """

    FORMAT_CHOICES = [
        ("JPEG", "JPG"),
        ("PNG", "PNG"),
        ("WEBP", "WebP"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.UUIDField(db_index=True, editable=False)

    original_filename = models.CharField(max_length=255)
    original_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    output_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)

    original_width = models.PositiveIntegerField()
    original_height = models.PositiveIntegerField()
    output_width = models.PositiveIntegerField()
    output_height = models.PositiveIntegerField()

    original_size = models.PositiveBigIntegerField(help_text="Bytes")
    optimized_size = models.PositiveBigIntegerField(help_text="Bytes")
    quality = models.PositiveSmallIntegerField()
    reduction_percent = models.FloatField(
        help_text="Positive = smaller than the original, negative = larger."
    )

    original_file = models.FileField(upload_to="originals/", max_length=255)
    optimized_file = models.FileField(upload_to="optimized/", max_length=255)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.get_output_format_display()})"

    @property
    def saved_bytes(self):
        """Bytes saved. Negative when the optimized file is larger."""
        return self.original_size - self.optimized_size

    @property
    def saved_bytes_abs(self):
        return abs(self.saved_bytes)

    @property
    def is_larger(self):
        return self.optimized_size > self.original_size

    @property
    def reduction_percent_abs(self):
        return abs(self.reduction_percent)

    @property
    def extension(self):
        return {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[self.output_format]

    @property
    def was_resized(self):
        return (self.original_width, self.original_height) != (
            self.output_width,
            self.output_height,
        )


@receiver(post_delete, sender=OptimizationRecord)
def delete_record_files(sender, instance, **kwargs):
    """Remove files from disk when a history entry is deleted."""
    for field in (instance.original_file, instance.optimized_file):
        if field and field.name:
            field.storage.delete(field.name)
