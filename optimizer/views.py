import io
import zipfile

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import OptimizeForm
from .models import OptimizationRecord
from .services.batch import process_batch
from .services.naming import download_filename


def _limits_context():
    return {
        "max_files": settings.OPTIMIZER_MAX_FILES,
        "max_file_mb": settings.OPTIMIZER_MAX_FILE_SIZE // (1024 * 1024),
        "max_file_bytes": settings.OPTIMIZER_MAX_FILE_SIZE,
        "default_quality": settings.OPTIMIZER_DEFAULT_QUALITY,
    }


@require_http_methods(["GET", "POST"])
def home(request):
    if request.method == "POST":
        form = OptimizeForm(request.POST, request.FILES)
        if form.is_valid():
            result = process_batch(form.cleaned_data["images"], form.processing_options())
            for filename, message in result.errors:
                messages.error(request, f"{filename}: {message}")
            for warning in result.warnings:
                messages.warning(request, warning)
            if result.records:
                return redirect("optimizer:results", batch_id=result.batch_id)
            # Nothing could be optimized: show the form again with the reasons.
            keep = ("quality", "width", "height", "preserve_aspect_ratio", "output_format")
            form = OptimizeForm(initial={key: form.cleaned_data[key] for key in keep})
            status = 400
        else:
            status = 400
        return render(
            request,
            "optimizer/home.html",
            {"form": form, **_limits_context()},
            status=status,
        )

    return render(
        request, "optimizer/home.html", {"form": OptimizeForm(), **_limits_context()}
    )


@require_GET
def results(request, batch_id):
    records = list(
        OptimizationRecord.objects.filter(batch_id=batch_id).order_by("created_at")
    )
    if not records:
        raise Http404("No results for this batch.")
    total_original = sum(r.original_size for r in records)
    total_optimized = sum(r.optimized_size for r in records)
    total_saved = total_original - total_optimized
    return render(
        request,
        "optimizer/results.html",
        {
            "records": records,
            "batch_id": batch_id,
            "total_original": total_original,
            "total_optimized": total_optimized,
            "total_saved": abs(total_saved),
            "total_is_larger": total_saved < 0,
            "total_percent": abs(total_saved / total_original * 100) if total_original else 0,
        },
    )


@require_GET
def history(request):
    paginator = Paginator(OptimizationRecord.objects.all(), 12)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "optimizer/history.html", {"page": page})


def _open_optimized(record):
    try:
        return record.optimized_file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("The optimized file is no longer available.")


@require_GET
def download(request, pk):
    record = get_object_or_404(OptimizationRecord, pk=pk)
    handle = _open_optimized(record)
    return FileResponse(
        handle,
        as_attachment=True,
        filename=download_filename(record.original_filename, record.extension),
    )


@require_GET
def download_zip(request, batch_id):
    records = list(
        OptimizationRecord.objects.filter(batch_id=batch_id).order_by("created_at")
    )
    if not records:
        raise Http404("No results for this batch.")

    buffer = io.BytesIO()
    used_names = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            try:
                with record.optimized_file.open("rb") as handle:
                    content = handle.read()
            except (FileNotFoundError, ValueError):
                continue  # file was removed from disk; skip it
            name = download_filename(record.original_filename, record.extension)
            stem, _, ext = name.rpartition(".")
            counter = 2
            while name.lower() in used_names:
                name = f"{stem}-{counter}.{ext}"
                counter += 1
            used_names.add(name.lower())
            archive.writestr(name, content)
    if not used_names:
        raise Http404("The optimized files are no longer available.")
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="optimized-images.zip"'
    return response


def _error_page(request, status, title, message):
    return render(
        request,
        "optimizer/error.html",
        {"status": status, "title": title, "message": message},
        status=status,
    )


def bad_request(request, exception=None):
    return _error_page(
        request,
        400,
        "We couldn't read that request",
        "The upload was incomplete or malformed. Please go back and try again.",
    )


def not_found(request, exception=None):
    return _error_page(
        request,
        404,
        "Page not found",
        "The page or file you're looking for doesn't exist or is no longer available.",
    )


def server_error(request):
    return _error_page(
        request,
        500,
        "Something went wrong",
        "An unexpected error occurred. Please try again.",
    )
