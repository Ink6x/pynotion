"""パフォーマンス回帰テスト (Phase 2-J)。

- ページツリーの Redis キャッシュとその無効化が正しく働くか
- ブロック数に対して詳細取得のクエリ数が一定 (N+1 が無い) か

クエリ数はセッション/認証で揺れるため、件数を変えても**等しい**ことを
比較して N+1 不在を示す (絶対数に依存しない)。
"""
import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from pages.models import Block, BlockType, Page
from pages.tests.helpers import post_json

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _query_count(client: Client, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        client.get(url)
    return len(ctx.captured_queries)


class TestPageTreeCache:
    def test_tree_served_from_cache_until_invalidated(
        self, authenticated_client: Client, user
    ) -> None:
        Page.objects.create_page(owner=user, title="最初")  # マネージャ経由 = 無効化なし

        first = authenticated_client.get("/api/pages/").json()["data"]["pages"]
        assert len(first) == 1  # ここでキャッシュに載る

        # API を介さず直接追加 → 無効化されないのでキャッシュが効き、見えない
        Page.objects.create_page(owner=user, title="直接追加")
        cached = authenticated_client.get("/api/pages/").json()["data"]["pages"]
        assert len(cached) == 1

        # API 経由の作成は無効化する → 直接追加分も含めて再計算される
        post_json(authenticated_client, "/api/pages/", {"title": "API経由"})
        fresh = authenticated_client.get("/api/pages/").json()["data"]["pages"]
        assert len(fresh) == 3

    def test_cache_hit_avoids_page_queries(self, authenticated_client: Client, user) -> None:
        Page.objects.create_page(owner=user, title="A")

        miss = _query_count(authenticated_client, "/api/pages/")
        hit = _query_count(authenticated_client, "/api/pages/")

        # キャッシュヒット時はツリー構築のための DB クエリが減る
        assert hit < miss


class TestNoNPlusOne:
    def test_detail_query_count_independent_of_block_count(
        self, authenticated_client: Client, user
    ) -> None:
        small = Page.objects.create_page(owner=user, title="少")
        Block.objects.create_block(page=small, type=BlockType.PARAGRAPH, text="x")

        large = Page.objects.create_page(owner=user, title="多")
        for i in range(40):
            Block.objects.create_block(page=large, type=BlockType.PARAGRAPH, text=str(i))

        # 認証/セッションのクエリ数を安定させるため一度叩いてから計測
        authenticated_client.get(f"/api/pages/{small.pk}/")

        small_q = _query_count(authenticated_client, f"/api/pages/{small.pk}/")
        large_q = _query_count(authenticated_client, f"/api/pages/{large.pk}/")

        # ブロックが 1 件でも 40 件でもクエリ数は同じ = N+1 なし
        assert small_q == large_q
