"""ページ全文検索 — DB バックエンドで実装を分岐する。

- **PostgreSQL**: pg_trgm トライグラム類似 (日本語など形態素解析なしで実用精度を
  出す主軸) と SearchVector / SearchRank (英数字トークン) のハイブリッド。
  マッチ箇所は SearchHeadline でスニペット化する。
- **SQLite (開発・テスト既定)**: `icontains` の部分一致フォールバック。
  ゼロ設定で動く開発体験を維持するため、PostgreSQL 専用機能には依存しない。

呼び出し側 (`api_pages.search`) はバックエンドを意識しない。戻り値の各 ``Page`` は
PostgreSQL 経路でのみ ``search_snippet`` 属性 (ハイライト済み抜粋) を持つ。
"""
from django.db import connection
from django.db.models import Q, QuerySet

from .models import Block, Page, accessible_page_ids

# トライグラム類似度のしきい値。これ未満は無関係とみなす。
# 部分一致 (icontains) は別途 OR で拾うため、ここは「曖昧一致」の感度のみを決める。
_TRIGRAM_THRESHOLD = 0.1


def search_pages(user, query: str) -> list[Page]:
    """``user`` が閲覧可能な生存ページから ``query`` に一致するものを返す。

    関連度の高い順。空クエリは空リスト。
    """
    query = query.strip()
    if not query:
        return []
    accessible = Page.objects.alive().filter(pk__in=accessible_page_ids(user))
    if connection.vendor == "postgresql":
        return _search_postgres(accessible, query)
    return _search_fallback(accessible, query)


def _search_fallback(base: QuerySet, query: str) -> list[Page]:
    """SQLite 等向けの部分一致検索。"""
    return list(
        base.filter(Q(title__icontains=query) | Q(blocks__text__icontains=query))
        .distinct()
        .order_by("-updated_at")
    )


def _search_postgres(base: QuerySet, query: str) -> list[Page]:  # pragma: no cover
    """PostgreSQL 向けハイブリッド検索 (pg_trgm + SearchVector)。

    SQLite では実行されないため、カバレッジは CI の PostgreSQL ジョブが担保する
    (``# pragma: no cover`` でローカル/既定ジョブのゲートから除外)。
    """
    from django.contrib.postgres.search import (
        SearchHeadline,
        SearchQuery,
        SearchRank,
        SearchVector,
        TrigramSimilarity,
    )

    # 本文マッチは to-many JOIN による行増殖 (= ページ重複) を避けるためサブクエリで解決。
    # タイトル類似度のみ annotate し、JOIN を発生させない。
    body_match_ids = (
        Block.objects.filter(page__in=base)
        .filter(Q(text__trigram_similar=query) | Q(text__icontains=query))
        .values_list("page_id", flat=True)
    )

    search_query = SearchQuery(query, config="simple")
    pages = (
        base.annotate(
            similarity=TrigramSimilarity("title", query),
            rank=SearchRank(SearchVector("title", config="simple"), search_query),
        )
        .filter(
            Q(title__icontains=query)
            | Q(similarity__gte=_TRIGRAM_THRESHOLD)
            | Q(pk__in=body_match_ids)
        )
        .annotate(
            snippet=SearchHeadline(
                "title",
                search_query,
                start_sel="<mark>",
                stop_sel="</mark>",
                config="simple",
            )
        )
        .order_by("-rank", "-similarity", "-updated_at")
    )

    results: list[Page] = []
    for page in pages:
        page.search_snippet = page.snippet or _body_snippet(page, query)
        results.append(page)
    return results


def _body_snippet(page: Page, query: str) -> str:  # pragma: no cover
    """本文中の最初のマッチ周辺を抜粋する (タイトルにヒットが無い場合の補助)。"""
    block = page.blocks.filter(text__icontains=query).first()
    if block is None:
        return page.title
    text = block.text
    idx = text.lower().find(query.lower())
    if idx < 0:
        return text[:80]
    start = max(0, idx - 30)
    return ("…" if start > 0 else "") + text[start : idx + len(query) + 50]
