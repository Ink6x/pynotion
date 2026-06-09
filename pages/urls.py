"""pages アプリの URL ルーティング。

API は django-ninja (``pages.api``) が ``/api/`` 配下を一括で提供する。
封筒・URL・ステータスは従来の関数ベース API と同一に保っている。
OpenAPI / Swagger UI は ``/api/docs``、スキーマは ``/api/openapi.json``。
"""
from django.urls import path

from databases.api import router as databases_router

from . import views
from .api import api

# データベースビューの API を同じ NinjaAPI へ登録する
# (封筒 renderer・例外ハンドラ・セッション認証を共有する)。
api.add_router("/databases/", databases_router)

urlpatterns = [
    path("", views.index, name="index"),
    path("api/", api.urls),
]
