from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("health", include("apps.core.health_urls")),
    path("api/v1/", include("apps.core.api_urls")),
    path("", include("apps.workspace.urls")),
]
