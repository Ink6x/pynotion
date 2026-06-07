"""認証フロー (サインアップ / ログイン / ログアウト) のテスト。"""
import pytest
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestCustomUser:
    def test_auth_user_model_is_accounts_user(self) -> None:
        user_model = get_user_model()
        assert user_model._meta.label == "accounts.User"

    def test_create_user(self) -> None:
        user = get_user_model().objects.create_user(
            username="carol", email="carol@example.com", password="pass-carol-123"
        )
        assert user.pk is not None
        assert user.check_password("pass-carol-123")


class TestSignup:
    def test_signup_creates_user_and_logs_in(self, client: Client) -> None:
        res = client.post(
            reverse("accounts:signup"),
            {
                "username": "dave",
                "password1": "complex-pass-9821",
                "password2": "complex-pass-9821",
            },
        )
        assert res.status_code == 302
        assert res.headers["Location"] == "/"
        user = get_user_model().objects.get(username="dave")
        assert client.session.get(SESSION_KEY) == str(user.pk)

    def test_signup_rejects_password_mismatch(self, client: Client) -> None:
        res = client.post(
            reverse("accounts:signup"),
            {
                "username": "eve",
                "password1": "complex-pass-9821",
                "password2": "different-pass-0000",
            },
        )
        assert res.status_code == 200  # フォーム再表示
        assert not get_user_model().objects.filter(username="eve").exists()

    def test_signup_page_renders(self, client: Client) -> None:
        res = client.get(reverse("accounts:signup"))
        assert res.status_code == 200


class TestLogin:
    def test_login_establishes_session(self, client: Client, user) -> None:
        res = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "test-pass-alice"},
        )
        assert res.status_code == 302
        assert client.session.get(SESSION_KEY) == str(user.pk)

    def test_login_with_wrong_password_fails(self, client: Client, user) -> None:
        res = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
        )
        assert res.status_code == 200  # フォーム再表示
        assert SESSION_KEY not in client.session


class TestLogout:
    def test_logout_clears_session(self, authenticated_client: Client) -> None:
        res = authenticated_client.post(reverse("accounts:logout"))
        assert res.status_code == 302
        # LOGOUT_REDIRECT_URL の named URL がログイン画面へ解決されること
        assert res.headers["Location"] == reverse("accounts:login")
        assert SESSION_KEY not in authenticated_client.session

    def test_logout_rejects_get(self, authenticated_client: Client) -> None:
        """Django 5 の LogoutView は POST のみ受け付ける(CSRF 対策)。"""
        res = authenticated_client.get(reverse("accounts:logout"))
        assert res.status_code == 405


class TestIndexRequiresLogin:
    def test_anonymous_is_redirected_to_login(self, client: Client) -> None:
        res = client.get("/")
        assert res.status_code == 302
        assert res.headers["Location"].startswith(reverse("accounts:login"))

    def test_authenticated_user_sees_app_shell(self, authenticated_client: Client) -> None:
        res = authenticated_client.get("/")
        assert res.status_code == 200
        assert 'id="sidebar"' in res.content.decode()
