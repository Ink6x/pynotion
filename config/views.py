"""インフラ用エンドポイント (ヘルスチェック)。"""
import logging

from django.conf import settings
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache

logger = logging.getLogger(__name__)


@never_cache
def healthz(request: HttpRequest) -> JsonResponse:
    """死活監視。DB (と設定時は Redis) の疎通を確認する。

    認証不要 (コンテナオーケストレータ / LB から叩かれる)。
    レスポンスに詳細は載せず、原因はサーバーログへ出す。
    """
    checks: dict[str, str] = {}
    healthy = True

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception:
        logger.exception("healthz: DB 疎通確認に失敗")
        checks["db"] = "error"
        healthy = False

    redis_url = getattr(settings, "REDIS_URL", None)
    if redis_url:
        try:
            import redis

            redis.Redis.from_url(
                redis_url, socket_connect_timeout=2, socket_timeout=2
            ).ping()
            checks["redis"] = "ok"
        except Exception:
            logger.exception("healthz: Redis 疎通確認に失敗")
            checks["redis"] = "error"
            healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "error", "checks": checks},
        status=200 if healthy else 503,
    )
