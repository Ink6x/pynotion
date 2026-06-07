"""HTML ビューのテスト。"""
import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


class TestIndex:
    def test_index_renders_app_shell(self, authenticated_client: Client) -> None:
        res = authenticated_client.get("/")
        assert res.status_code == 200
        html = res.content.decode()
        assert 'id="sidebar"' in html
        assert 'id="editor"' in html

    def test_index_sets_csrf_cookie(self, authenticated_client: Client) -> None:
        res = authenticated_client.get("/")
        assert "csrftoken" in res.cookies

    def test_index_requires_login(self, client: Client) -> None:
        res = client.get("/")
        assert res.status_code == 302
