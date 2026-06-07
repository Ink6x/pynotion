"""開発環境設定。ゼロ設定(環境変数なし)で起動できることを保証する。"""
import environ

from .base import *  # noqa: F403
from .base import BASE_DIR, env

# リポジトリ直下の .env を読む(存在しなければ無視。os.environ は上書きしない)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = True

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-dev-only-key-do-not-use-in-production",
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
