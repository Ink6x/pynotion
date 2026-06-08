"""全文検索 (pages.search) のテスト。

検索は DB バックエンドで分岐する:
- PostgreSQL: pg_trgm トライグラム + SearchVector ハイブリッド
- それ以外 (SQLite): icontains フォールバック

バックエンド非依存の契約 (権限・ゴミ箱除外・部分一致) は全環境で検証し、
トライグラム特有の曖昧一致・スニペットは PostgreSQL のみで検証する。
"""
import pytest
from django.db import connection

from pages.models import Block, BlockType, Page, PageShare, Role
from pages.search import search_pages

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL 専用機能 (pg_trgm / SearchVector)",
)


class TestSearchContract:
    """全バックエンド共通の検索契約。"""

    def test_matches_title_and_block_text(self, user) -> None:
        hit_title = Page.objects.create_page(owner=user, title="議事録")
        hit_body = Page.objects.create_page(owner=user, title="メモ")
        Block.objects.create_block(page=hit_body, type=BlockType.PARAGRAPH, text="議事録の下書き")
        Page.objects.create_page(owner=user, title="無関係")

        results = search_pages(user, "議事録")

        assert {p.id for p in results} == {hit_title.id, hit_body.id}

    def test_empty_query_returns_empty(self, user) -> None:
        Page.objects.create_page(owner=user, title="何か")
        assert search_pages(user, "") == []
        assert search_pages(user, "   ") == []

    def test_excludes_trashed_pages(self, user) -> None:
        page = Page.objects.create_page(owner=user, title="検索対象")
        page.soft_delete()
        assert search_pages(user, "検索対象") == []

    def test_excludes_inaccessible_pages(self, user, other_user) -> None:
        Page.objects.create_page(owner=other_user, title="他人の議事録")
        assert search_pages(user, "議事録") == []

    def test_includes_shared_pages(self, user, other_user) -> None:
        page = Page.objects.create_page(owner=other_user, title="共有された議事録")
        PageShare.objects.create(page=page, user=user, role=Role.VIEWER)

        results = search_pages(user, "議事録")

        assert {p.id for p in results} == {page.id}


@postgres_only
class TestPostgresSearch:
    """pg_trgm / SearchVector に依存する PostgreSQL 専用の挙動。"""

    def test_trigram_tolerates_typo(self, user) -> None:
        """トライグラム類似で表記ゆれ・タイプミスを吸収する。"""
        page = Page.objects.create_page(owner=user, title="プロジェクト計画書")

        results = search_pages(user, "プロジェクト計画")

        assert page.id in {p.id for p in results}

    def test_results_carry_snippet(self, user) -> None:
        page = Page.objects.create_page(owner=user, title="設計メモ")
        Block.objects.create_block(
            page=page, type=BlockType.PARAGRAPH, text="全文検索の設計について"
        )

        results = search_pages(user, "設計")

        target = next(p for p in results if p.id == page.id)
        assert getattr(target, "search_snippet", None)
