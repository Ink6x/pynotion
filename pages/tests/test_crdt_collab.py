"""Phase 4-D: 文字粒度の協調編集(CRDT)のサーバ側テスト。

ブラウザの Yjs クライアントの代わりに pycrdt(``BlockDoc``)で base64 更新を作り、
実際の WebSocket(``WebsocketCommunicator``)越しに 2 クライアントが同一テキストへ
収束し、``Block.text`` へ永続化されることを固定する。
"""
import base64

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from pages import crdt_store
from pages.crdt import BlockDoc
from pages.models import Block, Page, PageShare, Role
from pages.routing import websocket_urlpatterns

# --- crdt_store 単体 --------------------------------------------------------


@pytest.mark.django_db
class TestCrdtStore:
    def test_sync_seeds_from_block_text(self, user):
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        block.text = "種テキスト"
        block.save()
        # 空クライアントが state vector を送ると、種テキストを含む差分が返る
        client = BlockDoc()
        update_b64 = crdt_store.sync_update(
            block.id, block.text, base64.b64encode(client.state()).decode()
        )
        client.apply_update(base64.b64decode(update_b64))
        assert client.text == "種テキスト"

    def test_apply_update_merges_and_projects(self, user):
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        client = BlockDoc()
        client.apply_update(
            base64.b64decode(
                crdt_store.sync_update(block.id, "", base64.b64encode(client.state()).decode())
            )
        )
        before = client.state()
        client.insert(0, "あ")
        update_b64 = base64.b64encode(client.update_since(before)).decode()
        text = crdt_store.apply_update(block.id, "", update_b64)
        assert text == "あ"

    def test_flush_writes_text_and_bumps_version(self, user):
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        assert block.version == 1
        doc = BlockDoc("内容")
        from django.core.cache import cache

        cache.set(crdt_store._state_key(block.id), doc.update_since(), 60)
        assert crdt_store.flush(block.id) is True
        block.refresh_from_db()
        assert block.text == "内容"
        assert block.version == 2
        # もう一度 flush しても変化なし(同じテキスト)→ False
        assert crdt_store.flush(block.id) is False

    def test_flush_missing_state_is_noop(self, user):
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        assert crdt_store.flush(block.id) is False

    def test_maybe_flush_throttles(self, user):
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        doc = BlockDoc("x")
        from django.core.cache import cache

        cache.set(crdt_store._state_key(block.id), doc.update_since(), 60)
        assert crdt_store.maybe_flush(block.id, now=0.0) is True  # 初回は通す
        assert crdt_store.maybe_flush(block.id, now=1.0) is False  # 間隔内は抑制
        # 間隔を超えれば再度通す(テキスト変化が無ければ flush 自体は False)
        assert crdt_store.maybe_flush(block.id, now=5.0) is False


# --- WebSocket 越しの協調編集 ----------------------------------------------


def _ws_app():
    return URLRouter(websocket_urlpatterns)


@database_sync_to_async
def _make_user(username):
    return get_user_model().objects.create_user(username=username, password="pw-12345")


@database_sync_to_async
def _make_page(owner):
    return Page.objects.create_page(owner=owner)


@database_sync_to_async
def _first_block_id(page):
    return str(page.blocks.first().id)


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
    assert connected
    await comm.receive_json_from()  # presence init を捨てる
    return comm


class _Peer:
    """ブラウザ Yjs クライアントの代役(pycrdt)。"""

    def __init__(self):
        self.doc = BlockDoc()

    def state_b64(self):
        return base64.b64encode(self.doc.state()).decode()

    def apply_b64(self, update_b64):
        self.doc.apply_update(base64.b64decode(update_b64))

    def edit_b64(self, mutate):
        before = self.doc.state()
        mutate(self.doc)
        return base64.b64encode(self.doc.update_since(before)).decode()


async def _sync(comm, peer, block_id):
    await comm.send_json_to(
        {"type": "crdt_sync", "block_id": block_id, "state": peer.state_b64()}
    )
    msg = await comm.receive_json_from()
    assert msg["kind"] == "crdt_sync"
    peer.apply_b64(msg["update"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestCrdtCollaboration:
    async def test_two_editors_converge_and_persist(self):
        owner = await _make_user("crdt_owner")
        editor = await _make_user("crdt_editor")
        page = await _make_page(owner)
        await _share(page, editor, Role.EDITOR)
        block_id = await _first_block_id(page)

        a = await _connect(owner, page.id, client_id="a")
        b = await _connect(editor, page.id, client_id="b")
        # b の join 通知が a に届くので捨てる
        await a.receive_json_from()

        pa, pb = _Peer(), _Peer()
        await _sync(a, pa, block_id)
        await _sync(b, pb, block_id)

        # A が先頭に "Hello" を挿入
        up_a = pa.edit_b64(lambda d: d.insert(0, "Hello"))
        await a.send_json_to({"type": "crdt_update", "block_id": block_id, "update": up_a})
        # B は A の更新を受信して適用
        msg = await b.receive_json_from()
        assert msg["kind"] == "crdt_update"
        pb.apply_b64(msg["update"])
        assert pb.doc.text == "Hello"

        # B が末尾に " World" を挿入
        up_b = pb.edit_b64(lambda d: d.insert(5, " World"))
        await b.send_json_to({"type": "crdt_update", "block_id": block_id, "update": up_b})
        msg = await a.receive_json_from()
        pa.apply_b64(msg["update"])

        # 両者が収束
        assert pa.doc.text == pb.doc.text == "Hello World"

        await a.disconnect()
        await b.disconnect()

        # 切断時フラッシュで Block.text へ永続化されている
        block = await database_sync_to_async(Block.objects.get)(pk=block_id)
        assert block.text == "Hello World"

    async def test_nonexistent_page_is_rejected(self):
        import uuid

        owner = await _make_user("crdt_owner4")
        comm = WebsocketCommunicator(_ws_app(), f"/ws/pages/{uuid.uuid4()}/")
        comm.scope["user"] = owner
        connected, _ = await comm.connect()
        assert connected is False  # ページ不在は権限なしと同じ扱い
        await comm.disconnect()

    async def test_viewer_cannot_update_but_can_sync(self):
        owner = await _make_user("crdt_owner2")
        viewer = await _make_user("crdt_viewer2")
        page = await _make_page(owner)
        await _share(page, viewer, Role.VIEWER)
        block_id = await _first_block_id(page)

        # 先に owner が "seed" を確定させておく
        await database_sync_to_async(Block.objects.filter(pk=block_id).update)(text="seed")

        v = await _connect(viewer, page.id, client_id="v")
        pv = _Peer()
        # viewer も sync(読み取り)はできる
        await _sync(v, pv, block_id)
        assert pv.doc.text == "seed"

        # viewer の crdt_update は無視される(応答も永続化もされない)
        up_v = pv.edit_b64(lambda d: d.insert(0, "x"))
        await v.send_json_to({"type": "crdt_update", "block_id": block_id, "update": up_v})
        assert await v.receive_nothing(timeout=0.3) is True
        await v.disconnect()

    async def test_update_for_foreign_block_is_ignored(self):
        owner = await _make_user("crdt_owner3")
        page = await _make_page(owner)
        other_page = await _make_page(owner)
        foreign_block_id = await _first_block_id(other_page)

        a = await _connect(owner, page.id, client_id="a")
        pa = _Peer()
        # 別ページのブロックを sync しようとしても無視される(応答なし)
        await a.send_json_to(
            {"type": "crdt_sync", "block_id": foreign_block_id, "state": pa.state_b64()}
        )
        assert await a.receive_nothing(timeout=0.3) is True

        # 別ページのブロックへの crdt_update も無視される(認可スコープ外)
        up = pa.edit_b64(lambda d: d.insert(0, "z"))
        await a.send_json_to(
            {"type": "crdt_update", "block_id": foreign_block_id, "update": up}
        )
        assert await a.receive_nothing(timeout=0.3) is True

        # update が文字列でない(不正形式)場合も無視される
        await a.send_json_to(
            {"type": "crdt_update", "block_id": foreign_block_id, "update": None}
        )
        assert await a.receive_nothing(timeout=0.3) is True
        await a.disconnect()
