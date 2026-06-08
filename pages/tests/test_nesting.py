"""ブロックのネスト (Phase 3-E) のテスト。

- モデル: 並び順の (page, parent) スコープ、深さ・循環・ページ跨ぎの防止
- シリアライズ: フラット一覧 → ネストツリー
- API: parent_id 付き作成 / 移動 / collapsed 更新、ツリー取得のクエリ数固定
"""
import pytest
from django.test import Client

from pages.models import MAX_BLOCK_DEPTH, Block, BlockType, Page
from pages.serializers import serialize_block_tree
from pages.tests.helpers import patch_json, post_json

pytestmark = pytest.mark.django_db


class TestBlockNestingModel:
    def test_child_block_scoped_position(self, user) -> None:
        """並び順は (page, parent) 単位。親が違えば position は衝突してよい。"""
        page = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE, text="親")
        c1 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=parent)
        c2 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=parent)
        assert c1.parent_id == parent.pk
        assert list(parent.children.order_by("position")) == [c1, c2]

    def test_move_block_under_parent(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE, text="親")
        child = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="子")
        Block.objects.move(child, parent=parent, after=None)
        child.refresh_from_db()
        assert child.parent_id == parent.pk

    def test_move_to_root(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        child = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=parent)
        Block.objects.move(child, parent=None, after=None)
        child.refresh_from_db()
        assert child.parent_id is None

    def test_cannot_nest_under_self(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        with pytest.raises(ValueError):
            Block.objects.move(block, parent=block, after=None)

    def test_cannot_nest_under_descendant(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        a = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        b = Block.objects.create_block(page=page, type=BlockType.TOGGLE, parent=a)
        with pytest.raises(ValueError):
            Block.objects.move(a, parent=b, after=None)

    def test_cannot_nest_across_pages(self, user) -> None:
        page1 = Page.objects.create_page(owner=user)
        page2 = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page1, type=BlockType.TOGGLE)
        stray = Block.objects.create_block(page=page2, type=BlockType.PARAGRAPH)
        with pytest.raises(ValueError):
            Block.objects.move(stray, parent=parent, after=None)

    def test_depth_limit_enforced(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = None
        # ルート(深さ0)から MAX_BLOCK_DEPTH まではネスト可能
        chain = []
        for _ in range(MAX_BLOCK_DEPTH + 1):
            parent = Block.objects.create_block(
                page=page, type=BlockType.TOGGLE, parent=parent
            )
            chain.append(parent)
        # さらに 1 段深くしようとすると拒否される
        with pytest.raises(ValueError):
            Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=chain[-1])

    def test_subtree_height_counts_toward_depth(self, user) -> None:
        """移動するサブツリーの高さも深さ制限に算入される。"""
        page = Page.objects.create_page(owner=user)
        # 高さ 2 のサブツリー a>b>c
        a = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        b = Block.objects.create_block(page=page, type=BlockType.TOGGLE, parent=a)
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=b)
        assert a.subtree_height() == 2

    def test_after_must_be_sibling_of_parent(self, user) -> None:
        """別の親に属する after を基準にした採番は弾く (順序キーの不整合防止)。"""
        page = Page.objects.create_page(owner=user)
        p1 = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        p2 = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        under_p1 = Block.objects.create_block(
            page=page, type=BlockType.PARAGRAPH, parent=p1
        )
        # p2 配下に作ろうとしているのに after は p1 配下のブロック → 拒否
        with pytest.raises(ValueError):
            Block.objects.create_block(
                page=page, type=BlockType.PARAGRAPH, parent=p2, after=under_p1
            )

    def test_depth_and_descendants_helpers(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        a = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        b = Block.objects.create_block(page=page, type=BlockType.TOGGLE, parent=a)
        c = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=b)
        assert a.depth() == 0
        assert b.depth() == 1
        assert c.depth() == 2
        assert a.descendant_ids() == {b.pk, c.pk}


class TestSerializeBlockTree:
    def test_builds_nested_tree(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        page.blocks.all().delete()
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE, text="親")
        child = Block.objects.create_block(
            page=page, type=BlockType.PARAGRAPH, text="子", parent=parent
        )
        tree = serialize_block_tree(page.blocks.order_by("position"))
        assert len(tree) == 1
        assert tree[0]["id"] == str(parent.id)
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["id"] == str(child.id)

    def test_serialize_includes_collapsed_and_parent(self, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        child = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=parent)
        tree = serialize_block_tree([parent, child])
        node = tree[0]
        assert node["collapsed"] is False
        assert node["parent_id"] is None
        assert node["children"][0]["parent_id"] == str(parent.id)


@pytest.mark.integration
class TestNestingAPI:
    def test_create_nested_block(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = page.blocks.first()
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.id}/blocks/",
            {"type": "paragraph", "text": "子", "parent_id": str(parent.id)},
        )
        assert res.status_code == 201
        assert res.json()["data"]["block"]["parent_id"] == str(parent.id)

    def test_page_detail_returns_tree(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        parent = page.blocks.first()
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, parent=parent)
        res = authenticated_client.get(f"/api/pages/{page.id}/")
        assert res.status_code == 200
        blocks = res.json()["data"]["blocks"]
        assert len(blocks) == 1
        assert "children" in blocks[0]
        assert len(blocks[0]["children"]) == 1

    def test_move_block_under_parent_via_api(
        self, authenticated_client: Client, user
    ) -> None:
        page = Page.objects.create_page(owner=user)
        parent = page.blocks.first()
        child = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="子")
        res = post_json(
            authenticated_client,
            f"/api/blocks/{child.id}/move/",
            {"parent_id": str(parent.id)},
        )
        assert res.status_code == 200
        child.refresh_from_db()
        assert child.parent_id == parent.pk

    def test_move_to_root_via_api(self, authenticated_client: Client, user) -> None:
        """parent_id を明示 null で送るとルートへ繰り上がる。"""
        page = Page.objects.create_page(owner=user)
        parent = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        child = Block.objects.create_block(
            page=page, type=BlockType.PARAGRAPH, parent=parent
        )
        res = post_json(
            authenticated_client, f"/api/blocks/{child.id}/move/", {"parent_id": None}
        )
        assert res.status_code == 200
        child.refresh_from_db()
        assert child.parent_id is None

    def test_cycle_rejected_via_api(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        a = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        b = Block.objects.create_block(page=page, type=BlockType.TOGGLE, parent=a)
        res = post_json(
            authenticated_client, f"/api/blocks/{a.id}/move/", {"parent_id": str(b.id)}
        )
        assert res.status_code == 400

    def test_update_collapsed(self, authenticated_client: Client, user) -> None:
        page = Page.objects.create_page(owner=user)
        block = Block.objects.create_block(page=page, type=BlockType.TOGGLE)
        res = patch_json(
            authenticated_client, f"/api/blocks/{block.id}/", {"collapsed": True}
        )
        assert res.status_code == 200
        block.refresh_from_db()
        assert block.collapsed is True

    def test_page_detail_tree_query_count_is_constant(
        self, authenticated_client: Client, user, django_assert_num_queries
    ) -> None:
        """ツリー取得のクエリ数がブロック数に依存しない (N+1 なし)。"""
        page = Page.objects.create_page(owner=user)
        parent = page.blocks.first()
        # 深さは一定 (1) のまま子を多数ぶら下げ、ブロック数に対する N+1 を検出する
        for _ in range(20):
            Block.objects.create_block(
                page=page, type=BlockType.PARAGRAPH, parent=parent
            )
        url = f"/api/pages/{page.id}/"
        # ブロック数に依存しない固定クエリ数 (ツリーは 1 クエリ取得 + メモリ構築)
        with django_assert_num_queries(4):
            authenticated_client.get(url)
