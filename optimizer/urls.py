from django.urls import path

from . import views

app_name = "optimizer"

urlpatterns = [
    path("", views.home, name="home"),
    path("results/<uuid:batch_id>/", views.results, name="results"),
    path("results/<uuid:batch_id>/download.zip", views.download_zip, name="download_zip"),
    path("download/<uuid:pk>/", views.download, name="download"),
    path("history/", views.history, name="history"),
]
