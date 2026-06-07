"""本番環境設定。

必須環境変数(未設定なら起動失敗):
- DJANGO_SECRET_KEY
- DJANGO_ALLOWED_HOSTS (カンマ区切り)
- DATABASE_URL (例: postgres://user:pass@host:5432/dbname)

`manage.py check --deploy` をエラー 0 で通過することを CI で保証する。
"""
from .base import *  # noqa: F403
from .base import env

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
DATABASES = {"default": env.db("DATABASE_URL")}

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# 静的配信: WhiteNoise (圧縮 + マニフェストハッシュ)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# 構造化ログ (1 行 1 JSON、stdout へ)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "config.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "django.security": {"level": "WARNING"},
    },
}

# --- HTTPS / セキュリティ強化 (check --deploy 対応) ---
# TLS 終端がリバースプロキシより手前にあるローカル compose 検証では
# DJANGO_SECURE_SSL_REDIRECT=0 で無効化できる (本番デフォルトは有効)
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# preload リスト登録要件 (https://hstspreload.org/) を満たす 1 年で設定
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
