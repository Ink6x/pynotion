"""Page / Block / PageShare の JSON シリアライザ。"""
from collections import defaultdict
from collections.abc import Iterable

from .models import Block, Page, PageShare, PageSnapshot


def serialize_share(share: PageShare) -> dict:
    return {
        "user_id": share.user_id,
        "username": share.user.username,
        "role": share.role,
    }


def serialize_page(page: Page) -> dict:
    return {
        "id": str(page.id),
        "title": page.title,
        "icon": page.icon,
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "position": page.position,
        "updated_at": page.updated_at.isoformat(),
    }


def _count_blocks(tree: Iterable[dict]) -> int:
    """ネスト JSON 内のブロック総数。"""
    total = 0
    for node in tree or []:
        total += 1 + _count_blocks(node.get("children", []))
    return total


def serialize_snapshot(snapshot: PageSnapshot, *, include_data: bool = False) -> dict:
    data = {
        "id": str(snapshot.id),
        "created_at": snapshot.created_at.isoformat(),
        "created_by": snapshot.created_by.username if snapshot.created_by else None,
        "block_count": _count_blocks(snapshot.data),
    }
    if include_data:
        data["data"] = snapshot.data
    return data


def serialize_block(block: Block) -> dict:
    return {
        "id": str(block.id),
        "type": block.type,
        "text": block.text,
        "checked": block.checked,
        "collapsed": block.collapsed,
        "parent_id": str(block.parent_id) if block.parent_id else None,
        "position": block.position,
        "version": block.version,
    }


def serialize_block_tree(blocks: Iterable[Block]) -> list[dict]:
    """position 順のブロック一覧をネストしたツリーに変換する。

    ``serialize_tree`` (ページ) と同じ方式: 1 クエリで全ブロックを取得して
    メモリ上でツリーを組む (N+1 を避ける)。親が一覧に無いブロックはルート扱い。
    """
    block_list = list(blocks)
    known_ids = {block.id for block in block_list}
    by_parent: dict[object, list[Block]] = defaultdict(list)
    roots: list[Block] = []
    for block in block_list:
        if block.parent_id is None or block.parent_id not in known_ids:
            roots.append(block)
        else:
            by_parent[block.parent_id].append(block)

    def node(block: Block) -> dict:
        return {
            **serialize_block(block),
            "children": [node(child) for child in by_parent[block.id]],
        }

    return [node(block) for block in roots]


def serialize_tree(pages: Iterable[Page]) -> list[dict]:
    """position 順のページ一覧をネストしたツリーに変換する。

    親が一覧に含まれないページ (共有されたサブツリーのルートなど) は
    ルート扱いにする。
    """
    page_list = list(pages)
    known_ids = {page.id for page in page_list}
    by_parent: dict[object, list[Page]] = defaultdict(list)
    roots: list[Page] = []
    for page in page_list:
        if page.parent_id is None or page.parent_id not in known_ids:
            roots.append(page)
        else:
            by_parent[page.parent_id].append(page)

    def node(page: Page) -> dict:
        return {
            **serialize_page(page),
            "children": [node(child) for child in by_parent[page.id]],
        }

    return [node(page) for page in roots]
