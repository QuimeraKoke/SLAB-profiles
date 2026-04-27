from django.contrib import admin
from django.urls import path

from api.routers import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
