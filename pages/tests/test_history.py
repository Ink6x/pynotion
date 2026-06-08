"""バージョン履歴 (Phase 3-F) のテスト。

- capture / maybe_capture の時間スロットリングと保持件数
- diff_trees の差分計算
- restore のブロック再構築
- スナップショット API (一覧 / 詳細+diff / 復元 / 認可)
"""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from pages import history
from pages.models import Block, BlockType, Page, PageShare, PageSnapshot, Role
from pages.serializers import serialize_block_tree
from pages.tests.helpers import post_json

pytestmark = pytest.mark.django_db


class TestCapture:
    def test_capture_stores_current_tree(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="本文")
        snap = history.capture(page, user)
        assert snap.created_by == user
        assert history._flatten(snap.data)  # 何かしらブロックが入っている

    def test_maybe_capture_throttles_by_time(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        first = history.maybe_capture(page, user)
        assert first is not None
        # 直後はスロットリングされ撮られない
        assert history.maybe_capture(page, user) is None

    def test_maybe_capture_after_interval(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        old = history.capture(page, user)
        # 直近スナップショットを十分過去にずらす
        PageSnapshot.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(seconds=history.MIN_INTERVAL_SECONDS + 1)
        )
        assert history.maybe_capture(page, user) is not None

    def test_retention_limits_snapshot_count(self, user, monkeypatch) -> None:
        monkeypatch.setattr(history, "RETENTION", 3)
        page = Page.objects.create_page(owner=user)
        for _ in range(5):
            history.capture(page, user)
        assert page.snapshots.count() == 3


class TestDiff:
    def test_detects_added_removed_changed(self, user) -> None:
        before = [
            {"id": "a", "type": "paragraph", "text": "x", "position": "a", "children": []},
            {"id": "b", "type": "paragraph", "text": "y", "position": "b", "children": []},
        ]
        after = [
            {"id": "a", "type": "heading_1", "text": "x", "position": "a", "children": []},
            {"id": "c", "type": "paragraph", "text": "z", "position": "c", "children": []},
        ]
        d = history.diff_trees(before, after)
        assert d["counts"] == {"added": 1, "removed": 1, "changed": 1}
        assert d["added"][0]["id"] == "c"
        assert d["removed"][0]["id"] == "b"
        assert d["changed"][0]["fields"] == ["type"]

    def test_no_change(self, user) -> None:
        tree = [{"id": "a", "type": "paragraph", "text": "x", "position": "a", "children": []}]
        d = history.diff_trees(tree, tree)
        assert d["counts"] == {"added": 0, "removed": 0, "changed": 0}


class TestRestore:
    def test_restore_rebuilds_blocks(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        page.blocks.all().delete()
        b1 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="元1")
        b2 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="元2")
        snap = history.capture(page, user)

        # 状態を変える
        b1.text = "変更後"
        b1.save()
        b2.delete()
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="新規")

        history.restore(page, snap, user)
        texts = list(page.blocks.order_by("position").values_list("text", flat=True))
        assert texts == ["元1", "元2"]
        # 復元前の状態も履歴に残る (capture が呼ばれる)
        assert page.snapshots.count() >= 2

    def test_restore_sanitizes_unknown_block_type(self, user) -> None:
        """破損スナップショット (不正な type) は paragraph にフォールバックする。"""
        page = Page.objects.create_page(owner=user)
        snap = history.capture(page, user)
        # data を不正な type に改ざんしてから復元
        snap.data = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "type": "<script>",
                "text": "x",
                "checked": False,
                "collapsed": False,
                "parent_id": None,
                "position": "a0",
                "version": 1,
                "children": [],
            }
        ]
        snap.save()
        history.restore(page, snap, user)
        assert page.blocks.get().type == BlockType.PARAGRAPH

    def test_restore_preserves_nesting(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        page.blocks.all().delete()
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE, text="親")
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="子", parent=parent)
        snap = history.capture(page, user)
        page.blocks.all().delete()

        history.restore(page, snap, user)
        tree = serialize_block_tree(page.blocks.order_by("position"))
        assert len(tree) == 1
        assert tree[0]["text"] == "親"
        assert tree[0]["children"][0]["text"] == "子"


@pytest.mark.integration
class TestSnapshotAPI:
    def test_list_and_detail(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        snap = history.capture(page, user)
        res = authenticated_client.get(f"/api/pages/{page.id}/snapshots/")
        assert res.status_code == 200
        assert len(res.json()["data"]["snapshots"]) == 1

        detail = authenticated_client.get(
            f"/api/pages/{page.id}/snapshots/{snap.id}/"
        )
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert "data" in body["snapshot"]
        assert "diff" in body

    def test_restore_via_api(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        block.text = "初期"
        block.save()
        snap = history.capture(page, user)
        block.text = "編集後"
        block.save()

        res = post_json(
            authenticated_client,
            f"/api/pages/{page.id}/snapshots/{snap.id}/restore/",
            {},
        )
        assert res.status_code == 200
        block.refresh_from_db()
        assert block.text == "初期"

    def test_editing_creates_snapshot_at_session_boundary(
        self, authenticated_client: Client, user
    ) -> None:
        page = Page.objects.create_page(owner=user)
        block = page.blocks.first()
        # 最初の編集でセッション境界のスナップショットが残る
        from pages.tests.helpers import patch_json

        patch_json(authenticated_client, f"/api/blocks/{block.id}/", {"text": "編集1"})
        assert page.snapshots.count() == 1

    def test_viewer_cannot_restore(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=user)
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        snap = history.capture(page, user)
        client = Client()
        client.force_login(other_user)
        res = post_json(
            client, f"/api/pages/{page.id}/snapshots/{snap.id}/restore/", {}
        )
        assert res.status_code == 403

    def test_stranger_cannot_list(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=user)
        history.capture(page, user)
        client = Client()
        client.force_login(other_user)
        res = client.get(f"/api/pages/{page.id}/snapshots/")
        assert res.status_code == 404
