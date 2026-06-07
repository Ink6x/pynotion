"""Page / Block モデルのテスト。"""
import pytest

from pages.models import Block, BlockType, Page

pytestmark = pytest.mark.django_db


class TestPage:
    def test_create_root_page(self) -> None:
        page = Page.objects.create_page(title="はじめてのページ")
        assert page.title == "はじめてのページ"
        assert page.parent is None
        assert page.position
        assert page.is_deleted is False

    def test_create_child_page(self) -> None:
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        assert child.parent == parent
        assert list(parent.children.all()) == [child]

    def test_sibling_pages_ordered_by_position(self) -> None:
        first = Page.objects.create_page(title="1")
        second = Page.objects.create_page(title="2")
        third = Page.objects.create_page(title="3")
        roots = list(Page.objects.alive().roots())
        assert roots == [first, second, third]

    def test_soft_delete_moves_to_trash(self) -> None:
        page = Page.objects.create_page(title="削除対象")
        page.soft_delete()
        assert Page.objects.alive().count() == 0
        assert Page.objects.trashed().count() == 1
        assert page.deleted_at is not None

    def test_soft_delete_cascades_to_descendants(self) -> None:
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        grandchild = Page.objects.create_page(title="孫", parent=child)
        parent.soft_delete()
        for p in (parent, child, grandchild):
            p.refresh_from_db()
            assert p.is_deleted is True

    def test_restore_revives_page_and_descendants(self) -> None:
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        parent.soft_delete()
        parent.restore()
        child.refresh_from_db()
        assert parent.is_deleted is False
        assert child.is_deleted is False

    def test_soft_delete_preserves_already_trashed_child_timestamp(self) -> None:
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        child.soft_delete()
        original_deleted_at = child.deleted_at
        parent.soft_delete()
        child.refresh_from_db()
        assert child.deleted_at == original_deleted_at

    def test_restore_keeps_independently_trashed_children(self) -> None:
        """先に個別削除された子は、親の復元では復元されない。"""
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        child.soft_delete()
        parent.soft_delete()
        parent.restore()
        child.refresh_from_db()
        assert parent.is_deleted is False
        assert child.is_deleted is True

    def test_restore_child_of_trashed_parent_moves_to_root(self) -> None:
        """親がゴミ箱に残ったまま子だけ復元すると、ルートへ付け替えられる。"""
        parent = Page.objects.create_page(title="親")
        child = Page.objects.create_page(title="子", parent=parent)
        parent.soft_delete()
        child.refresh_from_db()
        child.restore()
        assert child.is_deleted is False
        assert child.parent is None
        assert child in list(Page.objects.alive().roots())

    def test_new_page_gets_default_paragraph_block(self) -> None:
        page = Page.objects.create_page(title="新規")
        assert page.blocks.count() == 1
        assert page.blocks.first().type == BlockType.PARAGRAPH


class TestBlock:
    def test_create_blocks_in_order(self) -> None:
        page = Page.objects.create_page(title="p")
        page.blocks.all().delete()
        b1 = Block.objects.create_block(page=page, type=BlockType.HEADING_1, text="見出し")
        b2 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="本文")
        assert list(page.blocks.order_by("position")) == [b1, b2]

    def test_insert_block_between(self) -> None:
        page = Page.objects.create_page(title="p")
        page.blocks.all().delete()
        b1 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="1")
        b2 = Block.objects.create_block(page=page, type=BlockType.PARAGRAPH, text="2")
        mid = Block.objects.create_block(
            page=page, type=BlockType.PARAGRAPH, text="間", after=b1
        )
        assert list(page.blocks.order_by("position")) == [b1, mid, b2]

    def test_todo_block_checked_state(self) -> None:
        page = Page.objects.create_page(title="p")
        block = Block.objects.create_block(page=page, type=BlockType.TO_DO, text="買い物")
        assert block.checked is False
        block.checked = True
        block.save()
        block.refresh_from_db()
        assert block.checked is True
