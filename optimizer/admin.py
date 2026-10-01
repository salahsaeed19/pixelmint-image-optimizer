from django.contrib import admin
from django.utils.html import format_html

from .models import OptimizationRecord


@admin.register(OptimizationRecord)
class OptimizationRecordAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = (
        "thumbnail",
        "original_filename",
        "original_format",
        "output_format",
        "original_dimensions",
        "output_dimensions",
        "original_size",
        "optimized_size",
        "quality",
        "reduction_percent",
        "created_at",
    )
    list_display_links = ("thumbnail", "original_filename")
    list_filter = ("output_format", "original_format", "created_at")
    search_fields = ("original_filename", "batch_id")
    readonly_fields = ("thumbnail", "created_at")
    list_per_page = 25

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if obj.optimized_file:
            return format_html(
                '<img src="{}" alt="" style="height:40px;width:40px;object-fit:cover;border-radius:6px">',
                obj.optimized_file.url,
            )
        return "-"

    @admin.display(description="Original size (px)")
    def original_dimensions(self, obj):
        return f"{obj.original_width}×{obj.original_height}"

    @admin.display(description="Output size (px)")
    def output_dimensions(self, obj):
        return f"{obj.output_width}×{obj.output_height}"
