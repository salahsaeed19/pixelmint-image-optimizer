from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("optimizer.urls")),
]

if settings.DEBUG:
    # Development-only serving of uploaded/optimized files for previews.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = "optimizer.views.bad_request"
handler404 = "optimizer.views.not_found"
handler500 = "optimizer.views.server_error"
