"""Page / Block / PageShare の JSON シリアライザ。"""
from collections import defaultdict
from collections.abc import Iterable

from .models import Block, Page, PageShare


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


def serialize_block(block: Block) -> dict:
    return {
        "id": str(block.id),
        "type": block.type,
        "text": block.text,
        "checked": block.checked,
        "position": block.position,
    }


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
