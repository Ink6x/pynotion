"""テスト共通フィクスチャ。

Phase 1-A(認証・RBAC)導入時に既存テストの移行コストを最小化するため、
認証済みクライアントをここで一元管理する。

- ``client``: pytest-django 組み込みの未認証クライアントをそのまま使う(再定義しない)
- ``authenticated_client``: ``user`` でログイン済みのクライアント(API テストの標準)
- ``user`` / ``other_user``: 所有者・第三者の 2 ユーザー(認可テスト用)

User の参照は ``get_user_model()`` 経由に統一する
(カスタムユーザー ``accounts.User`` 導入後も無変更で動く)。
フィクスチャが ``db`` を明示的に受け取るのは、マーカーなしでも
DB アクセスを許可するため(pytest-django の標準的な手法)。
"""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.test import Client


@pytest.fixture
def user(db) -> AbstractBaseUser:
    """ページ所有者となる標準ユーザー。"""
    return get_user_model().objects.create_user(
        username="alice",
        email="alice@example.com",
        password="test-pass-alice",
    )


@pytest.fixture
def other_user(db) -> AbstractBaseUser:
    """共有相手・権限なし検証用の第三者ユーザー。"""
    return get_user_model().objects.create_user(
        username="bob",
        email="bob@example.com",
        password="test-pass-bob",
    )


@pytest.fixture
def authenticated_client(user: AbstractBaseUser) -> Client:
    """``user`` としてログイン済みのクライアント。"""
    c = Client()
    c.force_login(user)
    return c
