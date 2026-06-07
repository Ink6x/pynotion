"""JSON API の統合テスト。"""
import json
import uuid

import pytest
from django.test import Client

from pages.models import Block, BlockType, Page

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def client() -> Client:
    return Client()


def post_json(client: Client, url: str, payload: dict) -> object:
    return client.post(url, json.dumps(payload), content_type="application/json")


def patch_json(client: Client, url: str, payload: dict) -> object:
    return client.patch(url, json.dumps(payload), content_type="application/json")


class TestPageTreeApi:
    def test_list_returns_nested_tree(self, client: Client) -> None:
        parent = Page.objects.create_page(title="親")
        Page.objects.create_page(title="子", parent=parent)
        res = client.get("/api/pages/")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        tree = body["data"]["pages"]
        assert len(tree) == 1
        assert tree[0]["title"] == "親"
        assert tree[0]["children"][0]["title"] == "子"

    def test_trashed_pages_excluded_from_tree(self, client: Client) -> None:
        page = Page.objects.create_page(title="削除済み")
        page.soft_delete()
        res = client.get("/api/pages/")
        assert res.json()["data"]["pages"] == []


class TestPageCrudApi:
    def test_create_page(self, client: Client) -> None:
        res = post_json(client, "/api/pages/", {"title": "新規ページ"})
        assert res.status_code == 201
        data = res.json()["data"]["page"]
        assert data["title"] == "新規ページ"
        page = Page.objects.get(pk=data["id"])
        assert page.blocks.count() == 1

    def test_create_child_page(self, client: Client) -> None:
        parent = Page.objects.create_page(title="親")
        res = post_json(client, "/api/pages/", {"title": "子", "parent_id": str(parent.pk)})
        assert res.status_code == 201
        assert res.json()["data"]["page"]["parent_id"] == str(parent.pk)

    def test_detail_returns_page_and_blocks(self, client: Client) -> None:
        page = Page.objects.create_page(title="詳細")
        res = client.get(f"/api/pages/{page.pk}/")
        body = res.json()["data"]
        assert body["page"]["title"] == "詳細"
        assert len(body["blocks"]) == 1

    def test_update_title_and_icon(self, client: Client) -> None:
        page = Page.objects.create_page(title="旧")
        res = patch_json(client, f"/api/pages/{page.pk}/", {"title": "新", "icon": "📝"})
        assert res.status_code == 200
        page.refresh_from_db()
        assert page.title == "新"
        assert page.icon == "📝"

    def test_delete_moves_to_trash(self, client: Client) -> None:
        page = Page.objects.create_page(title="ゴミ箱へ")
        res = client.delete(f"/api/pages/{page.pk}/")
        assert res.status_code == 200
        page.refresh_from_db()
        assert page.is_deleted is True

    def test_restore_from_trash(self, client: Client) -> None:
        page = Page.objects.create_page(title="復元")
        page.soft_delete()
        res = post_json(client, f"/api/pages/{page.pk}/restore/", {})
        assert res.status_code == 200
        page.refresh_from_db()
        assert page.is_deleted is False

    def test_permanent_delete_requires_trashed(self, client: Client) -> None:
        page = Page.objects.create_page(title="完全削除")
        res = client.delete(f"/api/pages/{page.pk}/permanent/")
        assert res.status_code == 400
        page.soft_delete()
        res = client.delete(f"/api/pages/{page.pk}/permanent/")
        assert res.status_code == 200
        assert not Page.objects.filter(pk=page.pk).exists()

    def test_trash_list(self, client: Client) -> None:
        page = Page.objects.create_page(title="ゴミ")
        page.soft_delete()
        res = client.get("/api/pages/trash/")
        titles = [p["title"] for p in res.json()["data"]["pages"]]
        assert titles == ["ゴミ"]

    def test_missing_page_returns_404(self, client: Client) -> None:
        res = client.get(f"/api/pages/{uuid.uuid4()}/")
        assert res.status_code == 404
        assert res.json()["ok"] is False


class TestPageMoveApi:
    def test_move_to_new_parent(self, client: Client) -> None:
        a = Page.objects.create_page(title="A")
        b = Page.objects.create_page(title="B")
        res = post_json(client, f"/api/pages/{b.pk}/move/", {"parent_id": str(a.pk)})
        assert res.status_code == 200
        b.refresh_from_db()
        assert b.parent == a

    def test_move_into_own_descendant_rejected(self, client: Client) -> None:
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        res = post_json(client, f"/api/pages/{parent.pk}/move/", {"parent_id": str(child.pk)})
        assert res.status_code == 400

    def test_reorder_after_sibling(self, client: Client) -> None:
        a = Page.objects.create_page(title="A")
        b = Page.objects.create_page(title="B")
        c = Page.objects.create_page(title="C")
        res = post_json(client, f"/api/pages/{a.pk}/move/", {"after_id": str(b.pk)})
        assert res.status_code == 200
        roots = [p.title for p in Page.objects.alive().roots()]
        assert roots == ["B", "A", "C"]


class TestBlockApi:
    def test_create_block(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        res = post_json(
            client,
            f"/api/pages/{page.pk}/blocks/",
            {"type": "heading_1", "text": "見出し"},
        )
        assert res.status_code == 201
        assert res.json()["data"]["block"]["type"] == "heading_1"

    def test_create_block_after(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        first = page.blocks.first()
        res = post_json(
            client,
            f"/api/pages/{page.pk}/blocks/",
            {"type": "paragraph", "text": "次", "after_id": str(first.pk)},
        )
        assert res.status_code == 201
        texts = [b.text for b in page.blocks.order_by("position")]
        assert texts == ["", "次"]

    def test_invalid_block_type_rejected(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        res = post_json(client, f"/api/pages/{page.pk}/blocks/", {"type": "unknown"})
        assert res.status_code == 400

    def test_update_block(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        block = page.blocks.first()
        res = patch_json(
            client,
            f"/api/blocks/{block.pk}/",
            {"type": "to_do", "text": "やること", "checked": True},
        )
        assert res.status_code == 200
        block.refresh_from_db()
        assert block.type == BlockType.TO_DO
        assert block.checked is True

    def test_delete_block(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        block = page.blocks.first()
        res = client.delete(f"/api/blocks/{block.pk}/")
        assert res.status_code == 200
        assert page.blocks.count() == 0

    def test_move_block_to_top(self, client: Client) -> None:
        page = Page.objects.create_page(title="p")
        page.blocks.all().delete()
        b1 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="1")
        b2 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="2")
        res = post_json(client, f"/api/blocks/{b2.pk}/move/", {"after_id": None})
        assert res.status_code == 200
        texts = [b.text for b in page.blocks.order_by("position")]
        assert texts == ["2", "1"]


class TestSearchApi:
    def test_search_by_title_and_block_text(self, client: Client) -> None:
        page1 = Page.objects.create_page(title="議事録")
        page2 = Page.objects.create_page(title="メモ")
        Block.objects.create_block(page=page2, type=BlockType.PARAGRAPH, text="議事録の下書き")
        Page.objects.create_page(title="無関係")
        res = client.get("/api/search/", {"q": "議事録"})
        ids = {p["id"] for p in res.json()["data"]["pages"]}
        assert ids == {str(page1.pk), str(page2.pk)}

    def test_search_excludes_trashed(self, client: Client) -> None:
        page = Page.objects.create_page(title="検索対象")
        page.soft_delete()
        res = client.get("/api/search/", {"q": "検索"})
        assert res.json()["data"]["pages"] == []

    def test_empty_query_returns_empty(self, client: Client) -> None:
        res = client.get("/api/search/", {"q": ""})
        assert res.json()["data"]["pages"] == []


class TestValidation:
    def test_invalid_json_body(self, client: Client) -> None:
        res = client.post("/api/pages/", "not-json", content_type="application/json")
        assert res.status_code == 400
        assert res.json()["ok"] is False
