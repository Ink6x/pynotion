"""開発環境設定。ゼロ設定(環境変数なし)で起動できることを保証する。"""
import environ

from .base import *  # noqa: F403
from .base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, env, with_postgres_app

# リポジトリ直下の .env を読む(存在しなければ無視。os.environ は上書きしない)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = True

# dev は collectstatic せずに配信する (STATIC_ROOT 未作成の警告も抑止)。
# USE_FINDERS で STATICFILES_DIRS から直接配信する (E2E の live_server でも
# collectstatic なしに /static/ が解決できる)。
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-dev-only-key-do-not-use-in-production",
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# 既定は SQLite (ゼロ設定)。DATABASE_URL を渡せば PostgreSQL 等へ切り替えられる
# (dj-database-url 互換)。CI の PostgreSQL ジョブやローカルでの全文検索検証で使う。
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

INSTALLED_APPS = with_postgres_app(INSTALLED_APPS, DATABASES)

# django-debug-toolbar (クエリ計測・N+1 発見)。
# テスト実行時のクエリ数計測やレスポンスへの干渉を避けるため、既定では無効。
# `DEBUG_TOOLBAR=1 python manage.py runserver` で有効化する。
ENABLE_DEBUG_TOOLBAR = env.bool("DEBUG_TOOLBAR", default=False)
if ENABLE_DEBUG_TOOLBAR:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
    INTERNAL_IPS = ["127.0.0.1"]
