"""pages アプリの URL ルーティング。

API は django-ninja (``pages.api``) が ``/api/`` 配下を一括で提供する。
封筒・URL・ステータスは従来の関数ベース API と同一に保っている。
OpenAPI / Swagger UI は ``/api/docs``、スキーマは ``/api/openapi.json``。
"""
from django.urls import path

from . import views
from .api import api

urlpatterns = [
    path("", views.index, name="index"),
    path("api/", api.urls),
]
