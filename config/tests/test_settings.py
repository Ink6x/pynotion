"""settings 分割 (base / dev / prod) の検証。

prod は環境変数必須・セキュリティ設定有効、dev はローカルで
ゼロ設定起動できることを保証する。モジュールを reload して
環境変数の反映を確認する(django.conf.settings には影響しない)。
"""
import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

pytestmark = pytest.mark.unit

PROD_ENV = {
    "DJANGO_SECRET_KEY": "x" * 60,
    "DJANGO_ALLOWED_HOSTS": "example.com",
    "DATABASE_URL": "sqlite:///prod-check.sqlite3",
}


def _reload(module_name: str, monkeypatch, env: dict[str, str | None]):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _reload_prod(monkeypatch, **overrides):
    return _reload("config.settings.prod", monkeypatch, {**PROD_ENV, **overrides})


class TestProdSettings:
    def test_debug_is_false(self, monkeypatch) -> None:
        prod = _reload_prod(monkeypatch)
        assert prod.DEBUG is False

    def test_secret_key_is_required(self, monkeypatch) -> None:
        with pytest.raises(ImproperlyConfigured):
            _reload_prod(monkeypatch, DJANGO_SECRET_KEY=None)

    def test_allowed_hosts_is_required(self, monkeypatch) -> None:
        with pytest.raises(ImproperlyConfigured):
            _reload_prod(monkeypatch, DJANGO_ALLOWED_HOSTS=None)

    def test_database_url_is_required(self, monkeypatch) -> None:
        with pytest.raises(ImproperlyConfigured):
            _reload_prod(monkeypatch, DATABASE_URL=None)

    def test_security_hardening_flags(self, monkeypatch) -> None:
        prod = _reload_prod(monkeypatch)
        assert prod.SECURE_SSL_REDIRECT is True
        assert prod.SESSION_COOKIE_SECURE is True
        assert prod.CSRF_COOKIE_SECURE is True
        # preload リスト登録要件: HSTS 1 年以上 + PRELOAD 有効
        assert prod.SECURE_HSTS_SECONDS >= 60 * 60 * 24 * 365
        assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert prod.SECURE_HSTS_PRELOAD is True
        assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True

    def test_allowed_hosts_parsed_as_list(self, monkeypatch) -> None:
        prod = _reload_prod(monkeypatch, DJANGO_ALLOWED_HOSTS="a.example.com,b.example.com")
        assert prod.ALLOWED_HOSTS == ["a.example.com", "b.example.com"]


class TestDevSettings:
    def test_debug_defaults_to_true(self, monkeypatch) -> None:
        dev = _reload("config.settings.dev", monkeypatch, {"DJANGO_SECRET_KEY": None})
        assert dev.DEBUG is True

    def test_runs_without_any_env(self, monkeypatch) -> None:
        """dev はゼロ設定で起動できる(SECRET_KEY デフォルト・SQLite)。"""
        dev = _reload(
            "config.settings.dev",
            monkeypatch,
            {"DJANGO_SECRET_KEY": None, "DJANGO_ALLOWED_HOSTS": None, "DATABASE_URL": None},
        )
        assert dev.SECRET_KEY
        assert dev.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
