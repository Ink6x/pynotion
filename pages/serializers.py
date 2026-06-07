"""Page / Block の JSON シリアライザ。"""
from collections import defaultdict
from collections.abc import Iterable

from .models import Block, Page


def serialize_page(page: Page) -> dict:
    return {
        "id": str(page.id),
        "title": page.title,
        "icon": page.icon,
        "parent_id": str(page.parent_id) if page.parent_id else None,
        "position": page.position,
        "updated_at": page.updated_at.isoformat(),
    }


def serialize_block(block: Block) -> dict:
    return {
        "id": str(block.id),
        "type": block.type,
        "text": block.text,
        "checked": block.checked,
        "position": block.position,
    }


def serialize_tree(pages: Iterable[Page]) -> list[dict]:
    """position 順のページ一覧をネストしたツリーに変換する。"""
    by_parent: dict[object, list[Page]] = defaultdict(list)
    for page in pages:
        by_parent[page.parent_id].append(page)

    def node(page: Page) -> dict:
        return {
            **serialize_page(page),
            "children": [node(child) for child in by_parent[page.id]],
        }

    return [node(page) for page in by_parent[None]]
