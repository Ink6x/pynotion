"""ASGI エントリポイント。

HTTP は従来どおり Django が処理し、WebSocket は Channels の
``AuthMiddlewareStack`` (セッション認証) → ``URLRouter`` → 各 Consumer へ振り分ける。
``ProtocolTypeRouter`` で両プロトコルを 1 つの ASGI アプリに束ねる。
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# get_asgi_application() を Channels の import より先に呼び、アプリレジストリを
# 初期化しておく (Consumer がモデルを参照するため)。
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from pages.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Origin 検証 (ALLOWED_HOSTS) → セッション認証 → ルーティング
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
