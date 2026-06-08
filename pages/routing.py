"""WebSocket ルーティング (Channels)。"""
from django.urls import path

from .consumers import PageConsumer

websocket_urlpatterns = [
    # ページ単位の同期チャンネル。閲覧権限があれば購読できる。
    path("ws/pages/<uuid:page_id>/", PageConsumer.as_asgi()),
]
