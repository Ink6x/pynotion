"""WebSocket Consumer — ページ単位のリアルタイム同期。

設計の要:
- **REST が信頼できる単一の源 (source of truth)**。ブロックの作成 / 更新 / 削除 /
  移動はすべて既存の django-ninja API が処理し、認可・レート制限・楽観ロックも
  そこで効く。WebSocket は「変更のブロードキャスト受信」と「プレゼンス」に専念する
  ため、認可ロジックを二重に持たない (= WebSocket 経由の不正書き込み口を作らない)。
- 閲覧権限 (viewer 以上) があれば購読でき、**viewer は受信専用**。書き込みは
  そもそも WebSocket では受け付けないので、ロールに関わらず変更は注入できない。
- 同じ ``client_id`` から来たイベントは送信元クライアントには返さない
  (自分の変更を二重適用しないためのエコー除去)。
"""
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

# クローズコード (WebSocket): 認証なし / 権限なし
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403

PRESENCE_TTL = 3600


def _group_name(page_id) -> str:
    return f"page_{page_id}"


def _presence_key(page_id) -> str:
    return f"presence:{page_id}"


class PageConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        self.user = self.scope.get("user")
        self.page_id = self.scope["url_route"]["kwargs"]["page_id"]
        self.group = _group_name(self.page_id)
        self.client_id = self._client_id_from_query()
        # group へ実際に join し presence を登録したかどうか。disconnect 時に
        # 「未参加で閉じた接続 (未認証/権限なし)」へ漏れ通知しないための番兵。
        self._joined_group = False

        if self.user is None or not self.user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.role = await self._resolve_role()
        if self.role is None:
            # 閲覧権限なし / ページ不在は同じ扱い (存在を漏らさない)
            await self.close(code=CLOSE_FORBIDDEN)
            return

        await self.channel_layer.group_add(self.group, self.channel_name)
        self._joined_group = True
        await self.accept()

        members = await self._add_presence()
        # 自分には現在のメンバー一覧を、他者には join を通知
        await self.send_json({"kind": "presence", "action": "init", "members": members})
        await self.channel_layer.group_send(
            self.group,
            {
                "type": "presence.event",
                "action": "join",
                "user": self.user.username,
                "members": members,
                "sender": self.channel_name,
            },
        )

    async def disconnect(self, code: int) -> None:
        # group へ join していない接続 (未認証/権限なしで閉じた) は何もしない。
        # presence にも登録していないため leave を漏らさない。
        if not getattr(self, "_joined_group", False):
            return
        members = await self._remove_presence()
        await self.channel_layer.group_discard(self.group, self.channel_name)
        await self.channel_layer.group_send(
            self.group,
            {
                "type": "presence.event",
                "action": "leave",
                "user": self.user.username,
                "members": members,
                "sender": self.channel_name,
            },
        )

    async def receive_json(self, content: dict, **kwargs) -> None:
        """クライアント → サーバ。

        ブロックの変更は WebSocket では受け付けない (REST が source of truth)。
        ここで扱うのはカーソル等のプレゼンス系のみ。viewer は送信できない。
        """
        msg_type = content.get("type")
        if msg_type == "cursor" and self.role != "viewer":
            await self.channel_layer.group_send(
                self.group,
                {
                    "type": "cursor.event",
                    "user": self.user.username,
                    "block_id": content.get("block_id"),
                    "sender": self.channel_name,
                },
            )
        # それ以外 (未知 / viewer の書き込み試行) は黙って無視する

    # --- group メッセージ → クライアントへの転送 ----------------------------

    async def block_event(self, event: dict) -> None:
        """REST 側のブロック変更を購読者へ転送する。送信元クライアントには返さない。"""
        if event.get("client_id") and event["client_id"] == self.client_id:
            return
        await self.send_json(
            {
                "kind": "block_event",
                "action": event["action"],
                "data": event["data"],
            }
        )

    async def presence_event(self, event: dict) -> None:
        if event.get("sender") == self.channel_name:
            return
        await self.send_json(
            {
                "kind": "presence",
                "action": event["action"],
                "user": event["user"],
                "members": event["members"],
            }
        )

    async def cursor_event(self, event: dict) -> None:
        if event.get("sender") == self.channel_name:
            return
        await self.send_json(
            {"kind": "cursor", "user": event["user"], "block_id": event["block_id"]}
        )

    # --- ヘルパー -----------------------------------------------------------

    def _client_id_from_query(self) -> str | None:
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        values = qs.get("client_id")
        # 長さを制限する (任意長文字列をメモリ・全イベントに載せられないように)
        return values[0][:64] if values else None

    @database_sync_to_async
    def _resolve_role(self):
        from .models import Page

        page = Page.objects.alive().filter(pk=self.page_id).first()
        if page is None:
            return None
        role = page.effective_role(self.user)
        return role.value if role is not None else None

    # プレゼンスはキャッシュへの read-modify-write。複数ワーカー (本番 Redis) では
    # 同時 join/leave で取りこぼしがありうるが、次の join/leave で自己修復する割り切り。
    # また role は connect 時に固定するため、接続中に共有を剥奪されても切断までは
    # 受信が続く (書き込みは WebSocket では不可能なので影響は読み取りに限られる)。

    @sync_to_async
    def _add_presence(self) -> list[str]:
        key = _presence_key(self.page_id)
        members = dict(cache.get(key) or {})
        members[self.channel_name] = self.user.username
        cache.set(key, members, PRESENCE_TTL)
        return sorted(set(members.values()))

    @sync_to_async
    def _remove_presence(self) -> list[str]:
        key = _presence_key(self.page_id)
        members = dict(cache.get(key) or {})
        members.pop(self.channel_name, None)
        cache.set(key, members, PRESENCE_TTL)
        return sorted(set(members.values()))
