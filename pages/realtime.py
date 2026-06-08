"""REST 書き込み後にページ購読者へ変更をブロードキャストするヘルパー。

REST が source of truth。各書き込みエンドポイントは DB 反映が成功した後に
``broadcast_block_event`` を呼び、同一ページを購読している他クライアントへ
変更を通知する。チャネルレイヤ未設定 (テストの一部) でも落ちないよう握りつぶす。
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .consumers import _group_name


def broadcast_block_event(
    page_id, action: str, data: dict, *, client_id: str | None = None
) -> None:
    """ページ group へブロック変更を配信する。

    **同期コンテキスト専用**。``async_to_sync`` を使うため、実行中のイベントループ
    がある async コンテキストから直接呼ぶと例外になる。REST 経由では
    ``transaction.on_commit`` (同期で実行される) からのみ呼んでいる。async から
    使う場合は ``layer.group_send`` を直接 await すること。

    Args:
        page_id: 対象ページ id
        action: "created" / "updated" / "deleted" / "moved"
        data: クライアントへ渡すペイロード (シリアライズ済みブロック等)
        client_id: 変更元クライアント。購読側でのエコー除去に使う
    """
    layer = get_channel_layer()
    if layer is None:  # チャネルレイヤ未設定 (ごく一部の設定) では何もしない
        return
    async_to_sync(layer.group_send)(
        _group_name(page_id),
        {
            "type": "block.event",
            "action": action,
            "data": data,
            "client_id": client_id,
        },
    )
