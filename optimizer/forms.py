from django import forms
from django.conf import settings

from .services.image_processing import (
    MAX_QUALITY,
    MIN_QUALITY,
    OUTPUT_FORMAT_CHOICES,
    ProcessingOptions,
)


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.Field):
    """Collects several uploads. Per-file checks happen in the processing layer so
    one bad file doesn't discard the rest of the batch."""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = [f for f in (data or []) if f]
        if not files:
            raise forms.ValidationError("Choose at least one image to optimize.")
        limit = settings.OPTIMIZER_MAX_FILES
        if len(files) > limit:
            raise forms.ValidationError(
                f"You can optimize at most {limit} images at a time "
                f"(you selected {len(files)})."
            )
        return files


class OptimizeForm(forms.Form):
    images = MultipleImageField()
    quality = forms.IntegerField(
        min_value=MIN_QUALITY,
        max_value=MAX_QUALITY,
        initial=settings.OPTIMIZER_DEFAULT_QUALITY,
        error_messages={
            "min_value": f"Quality must be between {MIN_QUALITY} and {MAX_QUALITY}.",
            "max_value": f"Quality must be between {MIN_QUALITY} and {MAX_QUALITY}.",
            "invalid": "Quality must be a whole number.",
            "required": "Quality is required.",
        },
    )
    width = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=settings.OPTIMIZER_MAX_DIMENSION,
        error_messages={"invalid": "Width must be a whole number."},
    )
    height = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=settings.OPTIMIZER_MAX_DIMENSION,
        error_messages={"invalid": "Height must be a whole number."},
    )
    preserve_aspect_ratio = forms.BooleanField(required=False, initial=True)
    output_format = forms.ChoiceField(
        choices=[
            ("original", "Keep original format"),
            ("jpg", "JPG"),
            ("png", "PNG"),
            ("webp", "WebP"),
        ],
        initial="original",
    )

    def processing_options(self) -> ProcessingOptions:
        data = self.cleaned_data
        return ProcessingOptions(
            quality=data["quality"],
            width=data.get("width"),
            height=data.get("height"),
            preserve_aspect_ratio=data["preserve_aspect_ratio"],
            output_format=OUTPUT_FORMAT_CHOICES[data["output_format"]],
        )
