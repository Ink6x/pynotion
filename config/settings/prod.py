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

# --- HTTPS / セキュリティ強化 (check --deploy 対応) ---
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# preload リスト登録要件 (https://hstspreload.org/) を満たす 1 年で設定
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
