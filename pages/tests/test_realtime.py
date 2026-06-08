"""リアルタイム同期 (Phase 3 C-3a) のテスト。

- 楽観ロック: version 不一致で 409 (同期、テストクライアント)
- WebSocket Consumer: 認証・認可・ブロードキャスト・プレゼンス
  (channels の ``WebsocketCommunicator`` で検証)
"""
import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from pages.models import Block, BlockType, Page, PageShare, Role
from pages.realtime import broadcast_block_event
from pages.routing import websocket_urlpatterns
from pages.tests.helpers import patch_json

# --- 楽観ロック (同期) ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
class TestOptimisticLock:
    def test_stale_version_returns_409(self, authenticated_client, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        assert block.version == 1
        # 古い version を送ると競合
        res = patch_json(
            authenticated_client,
            f"/api/blocks/{block.id}/",
            {"text": "後勝ち", "version": 0},
        )
        assert res.status_code == 409
        assert res.json()["ok"] is False

    def test_matching_version_succeeds_and_bumps(self, authenticated_client, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        res = patch_json(
            authenticated_client,
            f"/api/blocks/{block.id}/",
            {"text": "更新", "version": 1},
        )
        assert res.status_code == 200
        assert res.json()["data"]["block"]["version"] == 2

    def test_update_without_version_skips_check(self, authenticated_client, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        res = patch_json(
            authenticated_client, f"/api/blocks/{block.id}/", {"text": "version なし"}
        )
        assert res.status_code == 200

    def test_collapsed_only_does_not_bump_version(
        self, authenticated_client, user
    ) -> None:
        page = Page.objects.create_page(owner=user)
        block = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        res = patch_json(
            authenticated_client, f"/api/blocks/{block.id}/", {"collapsed": True}
        )
        assert res.status_code == 200
        assert res.json()["data"]["block"]["version"] == 1


# --- WebSocket Consumer (非同期) --------------------------------------------


def _ws_app():
    return URLRouter(websocket_urlpatterns)


@database_sync_to_async
def _make_user(username: str):
    return get_user_model().objects.create_user(username=username, password="pw-12345")


@database_sync_to_async
def _make_page(owner):
    return Page.objects.create_page(owner=owner)


@database_sync_to_async
def _share(page, user, role):
    PageShare.objects.create(page=page, user=user, role=role)


async def _connect(user, page_id, client_id=None):
    path = f"/ws/pages/{page_id}/"
    if client_id:
        path += f"?client_id={client_id}"
    comm = WebsocketCommunicator(_ws_app(), path)
    comm.scope["user"] = user
    connected, _ = await comm.connect()
    return comm, connected


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestPageConsumer:
    async def test_unauthenticated_is_rejected(self) -> None:
        owner = await _make_user("owner1")
        page = await _make_page(owner)
        from django.contrib.auth.models import AnonymousUser

        comm = WebsocketCommunicator(_ws_app(), f"/ws/pages/{page.id}/")
        comm.scope["user"] = AnonymousUser()
        connected, _ = await comm.connect()
        assert connected is False
        await comm.disconnect()

    async def test_owner_connects_and_gets_presence(self) -> None:
        owner = await _make_user("owner2")
        page = await _make_page(owner)
        comm, connected = await _connect(owner, page.id)
        assert connected is True
        msg = await comm.receive_json_from()
        assert msg["kind"] == "presence"
        assert msg["action"] == "init"
        assert "owner2" in msg["members"]
        await comm.disconnect()

    async def test_no_access_is_rejected(self) -> None:
        owner = await _make_user("owner3")
        stranger = await _make_user("stranger3")
        page = await _make_page(owner)
        comm, connected = await _connect(stranger, page.id)
        assert connected is False
        await comm.disconnect()

    async def test_broadcast_reaches_subscriber(self) -> None:
        owner = await _make_user("owner4")
        page = await _make_page(owner)
        comm, _ = await _connect(owner, page.id)
        await comm.receive_json_from()  # presence init を捨てる

        await database_sync_to_async(broadcast_block_event)(
            page.id, "updated", {"block": {"id": "x"}}, client_id="other-client"
        )
        msg = await comm.receive_json_from()
        assert msg["kind"] == "block_event"
        assert msg["action"] == "updated"
        await comm.disconnect()

    async def test_own_client_id_is_not_echoed(self) -> None:
        owner = await _make_user("owner5")
        page = await _make_page(owner)
        comm, _ = await _connect(owner, page.id, client_id="me")
        await comm.receive_json_from()  # presence init

        # 自分の client_id のイベントは届かない
        await database_sync_to_async(broadcast_block_event)(
            page.id, "updated", {"block": {"id": "x"}}, client_id="me"
        )
        assert await comm.receive_nothing(timeout=0.3) is True
        await comm.disconnect()

    async def test_presence_join_and_leave_are_broadcast(self) -> None:
        owner = await _make_user("owner7")
        editor = await _make_user("editor7")
        page = await _make_page(owner)
        await _share(page, editor, Role.EDITOR)

        a, _ = await _connect(owner, page.id)
        await a.receive_json_from()  # init (自分のみ)

        b, _ = await _connect(editor, page.id)
        await b.receive_json_from()  # init
        # a は editor の join 通知を受け取る
        join = await a.receive_json_from()
        assert join["kind"] == "presence"
        assert join["action"] == "join"
        assert "editor7" in join["members"]

        await b.disconnect()
        leave = await a.receive_json_from()
        assert leave["action"] == "leave"
        assert "editor7" not in leave["members"]
        await a.disconnect()

    async def test_cursor_is_relayed_between_editors(self) -> None:
        owner = await _make_user("owner8")
        editor = await _make_user("editor8")
        page = await _make_page(owner)
        await _share(page, editor, Role.EDITOR)

        a, _ = await _connect(owner, page.id)
        await a.receive_json_from()  # init
        b, _ = await _connect(editor, page.id)
        await b.receive_json_from()  # init
        await a.receive_json_from()  # editor join

        await b.send_json_to({"type": "cursor", "block_id": "blk-1"})
        msg = await a.receive_json_from()
        assert msg["kind"] == "cursor"
        assert msg["user"] == "editor8"
        assert msg["block_id"] == "blk-1"
        await a.disconnect()
        await b.disconnect()

    async def test_viewer_cursor_is_ignored(self) -> None:
        owner = await _make_user("owner9")
        viewer = await _make_user("viewer9")
        page = await _make_page(owner)
        await _share(page, viewer, Role.VIEWER)

        a, _ = await _connect(owner, page.id)
        await a.receive_json_from()  # init
        v, _ = await _connect(viewer, page.id)
        await v.receive_json_from()  # init
        await a.receive_json_from()  # viewer join

        # viewer はカーソル送信しても他者へ中継されない (受信専用)
        await v.send_json_to({"type": "cursor", "block_id": "blk-x"})
        assert await a.receive_nothing(timeout=0.3) is True
        await a.disconnect()
        await v.disconnect()

    async def test_viewer_can_connect_and_receive(self) -> None:
        owner = await _make_user("owner6")
        viewer = await _make_user("viewer6")
        page = await _make_page(owner)
        await _share(page, viewer, Role.VIEWER)
        comm, connected = await _connect(viewer, page.id)
        assert connected is True
        await comm.receive_json_from()  # presence init
        await database_sync_to_async(broadcast_block_event)(
            page.id, "created", {"block": {"id": "y"}}
        )
        msg = await comm.receive_json_from()
        assert msg["kind"] == "block_event"
        await comm.disconnect()
