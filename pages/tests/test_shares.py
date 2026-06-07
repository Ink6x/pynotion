"""共有管理 API (/api/pages/<id>/shares/) のテスト。"""
import pytest
from django.test import Client

from pages.models import Page, PageShare, Role
from pages.tests.helpers import post_json

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def other_client(other_user) -> Client:
    c = Client()
    c.force_login(other_user)
    return c


class TestShareAuthentication:
    def test_unauthenticated_is_401(self, user, client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        assert client.get(f"/api/pages/{page.pk}/shares/").status_code == 401


class TestShareList:
    def test_owner_can_list_shares(
        self, user, other_user, authenticated_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        res = authenticated_client.get(f"/api/pages/{page.pk}/shares/")
        assert res.status_code == 200
        shares = res.json()["data"]["shares"]
        assert len(shares) == 1
        assert shares[0]["username"] == other_user.username
        assert shares[0]["role"] == "editor"

    def test_editor_cannot_list_shares(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        assert other_client.get(f"/api/pages/{page.pk}/shares/").status_code == 403


class TestShareCreate:
    def test_owner_can_share_page(
        self, user, other_user, authenticated_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": other_user.username, "role": "viewer"},
        )
        assert res.status_code == 201
        share = PageShare.objects.get(page=page, user=other_user)
        assert share.role == Role.VIEWER

    def test_share_is_upserted(self, user, other_user, authenticated_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": other_user.username, "role": "editor"},
        )
        assert res.status_code == 200
        assert PageShare.objects.get(page=page, user=other_user).role == Role.EDITOR
        assert PageShare.objects.filter(page=page).count() == 1

    def test_cannot_share_to_owner(self, user, authenticated_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": user.username, "role": "viewer"},
        )
        assert res.status_code == 400

    def test_unknown_username_is_400(self, user, authenticated_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": "no-such-user", "role": "viewer"},
        )
        assert res.status_code == 400

    def test_invalid_role_is_400(self, user, other_user, authenticated_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        res = post_json(
            authenticated_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": other_user.username, "role": "superadmin"},
        )
        assert res.status_code == 400

    def test_editor_cannot_manage_shares(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        res = post_json(
            other_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": other_user.username, "role": "full_access"},
        )
        assert res.status_code == 403

    def test_full_access_share_can_manage_shares(
        self, user, other_user, other_client: Client, django_user_model
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.FULL_ACCESS)
        third = django_user_model.objects.create_user(username="carol", password="pass-x-1")
        res = post_json(
            other_client,
            f"/api/pages/{page.pk}/shares/",
            {"username": third.username, "role": "viewer"},
        )
        assert res.status_code == 201


class TestShareDelete:
    def test_owner_can_remove_share(
        self, user, other_user, authenticated_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
        res = authenticated_client.delete(f"/api/pages/{page.pk}/shares/{other_user.pk}/")
        assert res.status_code == 200
        assert not PageShare.objects.filter(page=page).exists()

    def test_missing_share_is_404(self, user, other_user, authenticated_client: Client) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        res = authenticated_client.delete(f"/api/pages/{page.pk}/shares/{other_user.pk}/")
        assert res.status_code == 404

    def test_viewer_cannot_remove_share(
        self, user, other_user, other_client: Client
    ) -> None:
        page = Page.objects.create_page(owner=user, title="p")
        PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
        res = other_client.delete(f"/api/pages/{page.pk}/shares/{other_user.pk}/")
        assert res.status_code == 403
