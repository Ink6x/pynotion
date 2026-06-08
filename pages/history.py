"""ページのバージョン履歴 — スナップショットの取得・差分・復元。

設計:
- **取得**: 編集のたびにスナップショットを撮ると肥大化するため、
  「直近のスナップショットから ``MIN_INTERVAL`` 秒以上経っていれば撮る」
  という時間スロットリングで編集セッションの境界をおおまかに捉える。
- **保持**: ページごとに最新 ``RETENTION`` 件だけ残し、古いものは削除する。
- **差分**: 2 つのスナップショット (または現在の状態) を flatten した
  ``{id: block}`` で突き合わせ、追加 / 削除 / 変更を求める。
- **復元**: トランザクション内で現在のブロックを全削除し、スナップショットの
  ツリーから再構築する。復元自体も元に戻せるよう、復元前に現在状態を撮る。
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import MAX_BLOCK_DEPTH, Block, BlockType, Page, PageSnapshot
from .serializers import serialize_block_tree

# スナップショットを撮る最小間隔 (秒)。これ未満の連続編集はまとめる。
MIN_INTERVAL_SECONDS = 120
# ページごとの保持件数。超過分は古い順に削除する。
RETENTION = 50


def _current_tree(page: Page) -> list[dict]:
    return serialize_block_tree(page.blocks.order_by("position"))


def capture(page: Page, user=None) -> PageSnapshot:
    """現在のブロックツリーをスナップショットとして保存し、保持件数を整える。"""
    snapshot = PageSnapshot.objects.create(
        page=page, data=_current_tree(page), created_by=user
    )
    _enforce_retention(page)
    return snapshot


def maybe_capture(page: Page, user=None) -> PageSnapshot | None:
    """直近スナップショットから一定時間空いていれば撮る (時間スロットリング)。

    連続編集のたびに撮らないことでストレージ肥大を抑える。撮らなかった場合は
    None を返す。

    直近スナップショット行を ``select_for_update`` でロックし、同一ページへの
    同時書き込みで重複スナップショットができるのを防ぐ (最初の 1 件だけは
    ロック対象が無く競合しうるが、重複しても保持件数制御で吸収される)。
    """
    with transaction.atomic():
        latest = page.snapshots.select_for_update().first()  # ordering = -created_at
        if latest is not None:
            elapsed = timezone.now() - latest.created_at
            if elapsed < timedelta(seconds=MIN_INTERVAL_SECONDS):
                return None
        return capture(page, user)


def _enforce_retention(page: Page) -> None:
    keep_ids = list(
        page.snapshots.values_list("id", flat=True)[:RETENTION]
    )
    page.snapshots.exclude(id__in=keep_ids).delete()


# --- 差分 -------------------------------------------------------------------


def _flatten(tree: list[dict]) -> dict[str, dict]:
    """ネスト JSON を {block_id: block(without children)} へ平坦化する。"""
    flat: dict[str, dict] = {}

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            children = node.get("children", [])
            flat[node["id"]] = {k: v for k, v in node.items() if k != "children"}
            walk(children)

    walk(tree or [])
    return flat


# 差分で「変更あり」とみなす対象フィールド (位置や version の揺れは無視する)
_DIFF_FIELDS = ("type", "text", "checked", "collapsed", "parent_id")


def diff_trees(before: list[dict], after: list[dict]) -> dict:
    """2 つのブロックツリーの差分を返す。

    Returns:
        {"added": [block...], "removed": [block...],
         "changed": [{"before": block, "after": block, "fields": [...]}],
         "counts": {"added": n, "removed": n, "changed": n}}
    """
    a = _flatten(before)
    b = _flatten(after)
    added = [b[i] for i in b if i not in a]
    removed = [a[i] for i in a if i not in b]
    changed = []
    for i in a:
        if i not in b:
            continue
        fields = [f for f in _DIFF_FIELDS if a[i].get(f) != b[i].get(f)]
        if fields:
            changed.append({"before": a[i], "after": b[i], "fields": fields})
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


# --- 復元 -------------------------------------------------------------------


def restore(page: Page, snapshot: PageSnapshot, user=None) -> None:
    """スナップショットの状態へページのブロックを復元する。

    復元は元に戻せるよう、先に現在状態のスナップショットを撮る。現在のブロックを
    全削除してからツリーを再構築する (id も復元するため衝突を避けて全削除が必要)。
    """
    with transaction.atomic():
        capture(page, user)  # 復元前の状態を履歴に残す
        page.blocks.all().delete()
        _rebuild(page, snapshot.data, parent=None)


def _rebuild(page: Page, nodes: list[dict], parent: "Block | None", depth: int = 0) -> None:
    """スナップショットのツリーから Block を再生成する (深さ優先)。

    スナップショット JSON は信頼境界として扱い、type を検証し深さを制限する
    (破損データによる不正な type 保存や無限再帰でのスタックオーバーフローを防ぐ)。
    """
    if depth > MAX_BLOCK_DEPTH:
        raise ValueError("スナップショットのネストが深すぎます")
    for node in nodes or []:
        btype = node.get("type", "paragraph")
        if btype not in BlockType.values:
            btype = BlockType.PARAGRAPH
        block = Block(
            id=node["id"],
            page=page,
            parent=parent,
            type=btype,
            text=node.get("text", ""),
            checked=node.get("checked", False),
            collapsed=node.get("collapsed", False),
            position=node["position"],
            version=node.get("version", 1),
        )
        block.save(force_insert=True)
        _rebuild(page, node.get("children", []), parent=block, depth=depth + 1)
