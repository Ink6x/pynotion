"""共通フィクスチャ (conftest.py) の検証。

Phase 1-A の認可導入に先立ち、認証済みクライアントの土台が
正しく機能することを保証する。
"""
import pytest
from django.contrib.auth import SESSION_KEY, get_user_model

pytestmark = [pytest.mark.django_db, pytest.mark.unit]


class TestUserFixtures:
    def test_user_is_persisted(self, user) -> None:
        assert get_user_model().objects.filter(pk=user.pk).exists()

    def test_user_and_other_user_are_distinct(self, user, other_user) -> None:
        assert user.pk != other_user.pk
        assert user.username != other_user.username


class TestAuthenticatedClient:
    def test_session_is_authenticated_as_user(self, authenticated_client, user) -> None:
        assert authenticated_client.session.get(SESSION_KEY) == str(user.pk)

    def test_unauthenticated_client_has_no_session(self, client) -> None:
        assert SESSION_KEY not in client.session
