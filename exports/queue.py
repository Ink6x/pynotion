"""エクスポートのジョブ投入。

本番(``EXPORTS_ASYNC`` 有効)は RQ(Redis 共有)へ投入し、ワーカーが処理する。
開発/テスト(既定)は同期実行する。同期パスは RQ / Redis を import しないため、
これらを base 依存に持たなくても動く(RQ は prod 依存)。
"""
from django.conf import settings


def _is_async() -> bool:
    return bool(getattr(settings, "EXPORTS_ASYNC", False))


def enqueue_export(export) -> None:
    """エクスポートジョブを投入する(非同期 or 同期)。"""
    if _is_async():
        _enqueue_async(export.id)
    else:
        from .tasks import run_export

        run_export(export.id)


def _enqueue_async(export_id) -> None:  # pragma: no cover - 本番のみ(Redis 必須)
    """RQ(Redis)へ投入する。本番のみ通る経路なので遅延 import する。"""
    import redis
    from rq import Queue

    connection = redis.from_url(settings.REDIS_URL)
    queue = Queue("exports", connection=connection)
    queue.enqueue("exports.tasks.run_export", export_id)
