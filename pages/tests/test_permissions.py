"""RBAC (Page.owner / PageShare / effective_role / API 認可) のテスト。"""
import pytest
from django.test import Client

from pages.models import Page, PageShare, Role, accessible_page_ids, role_satisfies
from pages.tests.helpers import patch_json, post_json

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def other_client(other_user) -> Client:
    c = Client()
    c.force_login(other_user)
    return c


class TestRoleOrdering:
    def test_role_weights_are_ordered(self) -> None:
        assert role_satisfies(Role.FULL_ACCESS, Role.VIEWER)
        assert role_satisfies(Role.EDITOR, Role.EDITOR)
        assert not role_satisfies(Role.VIEWER, Role.EDITOR)
        assert not role_satisfies(None, Role.VIEWER)


class TestEffectiveRole:
    def test_owner_has_full_access(self, user) -> None:
        page = Page.objects.create_page(owner=user, title="own")
        assert page.effective_role(user) == Role.FULL_ACCESS

    def test_no_share_returns_none(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=user, title="private")
        assert page.effective_role(other_user) is None

    def test_direct_share(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        assert page.effective_role(other_user) == Role.EDITOR

    def test_share_is_inherited_from_ancestor(self, user, other_user) -> None:
        root = Page.objects.create_page(owner=user, title="root")
        mid = Page.objects.create_page(owner=user, title="mid", parent=root)
        leaf = Page.objects.create_page(owner=user, title="leaf", parent=mid)
        PageShare.objects.create(page=root, user=other_user, role=Role.VIEWER)
        assert leaf.effective_role(other_user) == Role.VIEWER

    def test_strongest_role_wins(self, user, other_user) -> None:
        root = Page.objects.create_page(owner=user, title="root")
        child = Page.objects.create_page(owner=user, title="child", parent=root)
        PageShare.objects.create(page=root, user=other_user, role=Role.VIEWER)
        PageShare.objects.create(page=child, user=other_user, role=Role.EDITOR)
        assert child.effective_role(other_user) == Role.EDITOR

    def test_share_query_is_single_lookup(
        self, user, other_user, django_assert_num_queries
    ) -> None:
        """祖先が何段あっても PageShare の解決は 1 クエリ。

        祖先 id の収集は (深さ - 1) クエリ (直近の parent_id は
        インスタンスが保持)、共有の照合は page_id__in で 1 回。
        深さ 3 なら合計 3 クエリに収まる。
        """
        root = Page.objects.create_page(owner=user, title="r")
        a = Page.objects.create_page(owner=user, title="a", parent=root)
        b = Page.objects.create_page(owner=user, title="b", parent=a)
        PageShare.objects.create(page=root, user=other_user, role=Role.EDITOR)
        page = Page.objects.get(pk=b.pk)  # キャッシュなしの状態から測る
        with django_assert_num_queries(3):
            assert page.effective_role(other_user) == Role.EDITOR

    def test_effective_role_is_cached_per_instance(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        assert page.effective_role(other_user) == Role.VIEWER
        PageShare.objects.all().delete()
        # 同一インスタンスではキャッシュが効く (リクエスト内の二重計算防止)
        assert page.effective_role(other_user) == Role.VIEWER


class TestAccessiblePageIds:
    def test_includes_owned_and_shared_subtree(self, user, other_user) -> None:
        own = Page.objects.create_page(owner=other_user, title="own")
        shared_root = Page.objects.create_page(owner=user, title="shared")
        shared_child = Page.objects.create_page(owner=user, title="child", parent=shared_root)
        Page.objects.create_page(owner=user, title="unrelated")
        PageShare.objects.create(page=shared_root, user=other_user, role=Role.VIEWER)

        ids = accessible_page_ids(other_user)
        assert ids == {own.pk, shared_root.pk, shared_child.pk}


class TestApiAuthentication:
    def test_unauthenticated_api_returns_401(self, client: Client) -> None:
        res = client.get("/api/pages/")
        assert res.status_code == 401
        assert res.json()["ok"] is False


class TestApiAuthorization:
    """API ごとの認可マトリクス。"""

    def test_others_page_is_404(self, user, other_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="private")
        assert other_client.get(f"/api/pages/{page.pk}/").status_code == 404

    def test_viewer_can_read_but_not_edit(self, user, other_user, other_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        assert other_client.get(f"/api/pages/{page.pk}/").status_code == 200
        res = patch_json(other_client, f"/api/pages/{page.pk}/", {"title": "x"})
        assert res.status_code == 403
        assert other_client.delete(f"/api/pages/{page.pk}/").status_code == 403

    def test_editor_can_edit_but_not_permanent_delete(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        res = patch_json(other_client, f"/api/pages/{page.pk}/", {"title": "編集"})
        assert res.status_code == 200
        assert other_client.delete(f"/api/pages/{page.pk}/").status_code == 200  # soft delete
        assert other_client.delete(f"/api/pages/{page.pk}/permanent/").status_code == 403

    def test_full_access_share_can_permanent_delete(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.FULL_ACCESS)
        page.soft_delete()
        assert other_client.delete(f"/api/pages/{page.pk}/permanent/").status_code == 200
        assert not Page.objects.filter(pk=page.pk).exists()

    def test_viewer_cannot_create_or_edit_blocks(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        block = page.blocks.first()
        res = post_json(other_client, f"/api/pages/{page.pk}/blocks/", {"type": "paragraph"})
        assert res.status_code == 403
        patched = patch_json(other_client, f"/api/blocks/{block.pk}/", {"text": "x"})
        assert patched.status_code == 403

    def test_blocks_on_inaccessible_page_are_404(
        self, user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="private")
        block = page.blocks.first()
        patched = patch_json(other_client, f"/api/blocks/{block.pk}/", {"text": "x"})
        assert patched.status_code == 404

    def test_block_create_on_inaccessible_page_is_404(
        self, user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="private")
        res = post_json(other_client, f"/api/pages/{page.pk}/blocks/", {"type": "paragraph"})
        assert res.status_code == 404

    def test_editor_can_create_subpage_owned_by_tree_owner(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        res = post_json(
            other_client, "/api/pages/", {"title": "sub", "parent_id": str(page.pk)}
        )
        assert res.status_code == 201
        sub = Page.objects.get(pk=res.json()["data"]["page"]["id"])
        # 子ページの owner はツリー所有者を継承する
        assert sub.owner == user

    def test_viewer_cannot_create_subpage(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="shared")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        res = post_json(
            other_client, "/api/pages/", {"title": "sub", "parent_id": str(page.pk)}
        )
        assert res.status_code == 403

    def test_create_under_inaccessible_parent_is_400(
        self, user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="private")
        res = post_json(
            other_client, "/api/pages/", {"title": "sub", "parent_id": str(page.pk)}
        )
        # 存在を漏らさない: 「parent_id のページが見つかりません」
        assert res.status_code == 400

    def test_editor_cannot_move_shared_page_to_own_root(
        self, user, other_user, other_client: Client
    ) -> None:
        root = Page.objects.create_page(owner=user, title="root")
        child = Page.objects.create_page(owner=user, title="child", parent=root)
        PageShare.objects.create(page=root, user=other_user, role=Role.EDITOR)
        res = post_json(other_client, f"/api/pages/{child.pk}/move/", {"parent_id": None})
        assert res.status_code == 403

    def test_owner_can_move_page_to_root(self, user, authenticated_client: Client) -> None:
        root = Page.objects.create_page(owner=user, title="root")
        child = Page.objects.create_page(owner=user, title="child", parent=root)
        res = post_json(authenticated_client, f"/api/pages/{child.pk}/move/", {"parent_id": None})
        assert res.status_code == 200
        child.refresh_from_db()
        assert child.parent is None


class TestVisibilityFiltering:
    def test_tree_only_shows_accessible_pages(
        self, user, other_user, other_client: Client
    ) -> None:
        Page.objects.create_page(owner=user, title="秘密")
        shared = Page.objects.create_page(owner=user, title="共有")
        Page.objects.create_page(owner=user, title="共有の子", parent=shared)
        Page.objects.create_page(owner=other_user, title="自分の")
        PageShare.objects.create(page=shared, user=other_user, role=Role.VIEWER)

        res = other_client.get("/api/pages/")
        tree = res.json()["data"]["pages"]
        titles = {p["title"] for p in tree}
        # 共有サブツリーのルートはトップレベルに現れる
        assert titles == {"共有", "自分の"}
        shared_node = next(p for p in tree if p["title"] == "共有")
        assert [c["title"] for c in shared_node["children"]] == ["共有の子"]

    def test_search_excludes_inaccessible(self, user, other_user, other_client: Client) -> None:
        Page.objects.create_page(owner=user, title="議事録 秘密")
        shared = Page.objects.create_page(owner=user, title="議事録 共有")
        PageShare.objects.create(page=shared, user=other_user, role=Role.VIEWER)

        res = other_client.get("/api/search/", {"q": "議事録"})
        titles = [p["title"] for p in res.json()["data"]["pages"]]
        assert titles == ["議事録 共有"]

    def test_trash_shows_only_owned_pages(self, user, other_user, other_client: Client) -> None:
        mine = Page.objects.create_page(owner=other_user, title="自分のゴミ")
        mine.soft_delete()
        shared = Page.objects.create_page(owner=user, title="共有ゴミ")
        PageShare.objects.create(page=shared, user=other_user, role=Role.EDITOR)
        shared.soft_delete()

        res = other_client.get("/api/pages/trash/")
        titles = [p["title"] for p in res.json()["data"]["pages"]]
        assert titles == ["自分のゴミ"]
