"""pages アプリの URL ルーティング。"""
from django.urls import path

from . import api_blocks, api_pages, views

urlpatterns = [
    # アプリシェル
    path("", views.index, name="index"),
    # ページ API
    path("api/pages/", api_pages.page_collection),
    path("api/pages/trash/", api_pages.trash_list),
    path("api/pages/<uuid:page_id>/", api_pages.page_detail),
    path("api/pages/<uuid:page_id>/restore/", api_pages.page_restore),
    path("api/pages/<uuid:page_id>/permanent/", api_pages.page_permanent_delete),
    path("api/pages/<uuid:page_id>/move/", api_pages.page_move),
    # ブロック API
    path("api/pages/<uuid:page_id>/blocks/", api_blocks.block_collection),
    path("api/blocks/<uuid:block_id>/", api_blocks.block_detail),
    path("api/blocks/<uuid:block_id>/move/", api_blocks.block_move),
    # 検索 API
    path("api/search/", api_pages.search),
]
