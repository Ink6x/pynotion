"""カスタムユーザーモデル。

最初から AUTH_USER_MODEL を差し替えておくことで、
将来のプロフィール拡張をマイグレーション一発で行えるようにする。
"""
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """pynotion のユーザー。現時点では AbstractUser の最小拡張。"""

    class Meta:
        verbose_name = "ユーザー"
        verbose_name_plural = "ユーザー"
