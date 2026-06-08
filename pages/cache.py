"""ページツリーの Redis キャッシュ。

ユーザーごとに直列化済みツリーをキャッシュする。ツリーの内容は
「所有 + 共有されたページの階層・タイトル・アイコン」で決まるため、
ページの作成 / 改名 / 移動 / 削除・復元 / 共有変更で無効化する
(ブロック本文の編集はツリーに影響しないので無効化しない = 編集中もキャッシュが効く)。

無効化はグローバルな**世代カウンタ**を増やす方式。キャッシュキーに世代を
含めるため、インクリメント一発で全ユーザーのツリーが一斉に新キーへ移る
(古いキーは TTL で自然消滅)。個別キー削除より単純で、取りこぼしによる
スタる読み取りが構造的に起きない。精度より正しさと単純さを優先した割り切り。
"""
from django.conf import settings
from django.core.cache import cache

_GEN_KEY = "page_tree:gen"


def _generation() -> int:
    """現在の世代番号。未設定なら 1 で初期化する。"""
    gen = cache.get(_GEN_KEY)
    if gen is None:
        cache.add(_GEN_KEY, 1)
        gen = cache.get(_GEN_KEY) or 1
    return gen


def tree_cache_key(user) -> str:
    return f"page_tree:{user.pk}:{_generation()}"


def get_cached_tree(user):
    """キャッシュ済みツリー (list) を返す。未キャッシュなら None。"""
    return cache.get(tree_cache_key(user))


def set_cached_tree(user, tree) -> None:
    cache.set(tree_cache_key(user), tree, settings.PAGE_TREE_CACHE_TTL)


def invalidate_trees() -> None:
    """世代を進めて全ユーザーのツリーキャッシュを無効化する。"""
    try:
        cache.incr(_GEN_KEY)
    except ValueError:
        # キー未作成時 (incr は存在しないキーで ValueError)
        cache.set(_GEN_KEY, 1)
