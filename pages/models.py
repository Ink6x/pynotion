"""Page / Block — Notion のページとブロックを表すモデル。"""
import uuid

from django.db import models
from django.utils import timezone

from .ordering import key_between


class BlockType(models.TextChoices):
    """ブロックの種類(Notion API の type 名に準拠)。"""

    PARAGRAPH = "paragraph", "テキスト"
    HEADING_1 = "heading_1", "見出し1"
    HEADING_2 = "heading_2", "見出し2"
    HEADING_3 = "heading_3", "見出し3"
    TO_DO = "to_do", "ToDo リスト"
    BULLETED_LIST_ITEM = "bulleted_list_item", "箇条書きリスト"
    NUMBERED_LIST_ITEM = "numbered_list_item", "番号付きリスト"
    QUOTE = "quote", "引用"
    DIVIDER = "divider", "区切り線"
    CODE = "code", "コード"


class PageQuerySet(models.QuerySet):
    def alive(self) -> "PageQuerySet":
        return self.filter(is_deleted=False)

    def trashed(self) -> "PageQuerySet":
        return self.filter(is_deleted=True)

    def roots(self) -> "PageQuerySet":
        return self.filter(parent__isnull=True).order_by("position")


class PageManager(models.Manager.from_queryset(PageQuerySet)):
    def create_page(
        self,
        *,
        title: str = "",
        icon: str = "",
        parent: "Page | None" = None,
        after: "Page | None" = None,
    ) -> "Page":
        """ページを作成し、空の段落ブロックを 1 つ持たせる。"""
        position = self._next_position(parent=parent, after=after)
        page = self.create(title=title, icon=icon, parent=parent, position=position)
        Block.objects.create_block(page=page, type=BlockType.PARAGRAPH)
        return page

    def _next_position(self, *, parent: "Page | None", after: "Page | None") -> str:
        siblings = self.get_queryset().filter(parent=parent).order_by("position")
        if after is not None:
            following = siblings.filter(position__gt=after.position).first()
            return key_between(after.position, following.position if following else None)
        last = siblings.last()
        return key_between(last.position if last else None, None)

    def move(self, page: "Page", *, parent: "Page | None", after: "Page | None") -> None:
        """ページを parent の子として after の直後 (None なら先頭) に移動する。"""
        siblings = (
            self.get_queryset().filter(parent=parent).exclude(pk=page.pk).order_by("position")
        )
        if after is None:
            first = siblings.first()
            position = key_between(None, first.position if first else None)
        else:
            following = siblings.filter(position__gt=after.position).first()
            position = key_between(after.position, following.position if following else None)
        page.parent = parent
        page.position = position
        page.save(update_fields=["parent", "position", "updated_at"])


class Page(models.Model):
    """階層構造を持つページ。削除はソフトデリート(ゴミ箱)。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=16, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    position = models.CharField(max_length=255)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PageManager()

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(fields=["parent", "is_deleted", "position"]),
        ]

    def __str__(self) -> str:
        return self.title or "無題"

    def descendants(self) -> list["Page"]:
        """全ての子孫ページ。階層ごとにまとめて取得する (クエリ数 = 深さ)。"""
        result: list[Page] = []
        frontier = [self.pk]
        while frontier:
            children = list(Page.objects.filter(parent_id__in=frontier))
            result.extend(children)
            frontier = [child.pk for child in children]
        return result

    def soft_delete(self) -> None:
        """自身と未削除の子孫をゴミ箱へ移動する。

        既にゴミ箱にある子孫の deleted_at は上書きしない
        (個別削除の履歴と復元単位を保つため)。
        """
        now = timezone.now()
        pages = [self, *(p for p in self.descendants() if not p.is_deleted)]
        for page in pages:
            page.is_deleted = True
            page.deleted_at = now
        Page.objects.bulk_update(pages, ["is_deleted", "deleted_at"])

    def restore(self) -> None:
        """自身と「同時に削除された」子孫をゴミ箱から復元する。

        親より先に個別削除されていた子孫 (deleted_at が異なる) は
        ゴミ箱に残す。
        """
        marker = self.deleted_at
        pages = [
            self,
            *(p for p in self.descendants() if p.is_deleted and p.deleted_at == marker),
        ]
        for page in pages:
            page.is_deleted = False
            page.deleted_at = None
        Page.objects.bulk_update(pages, ["is_deleted", "deleted_at"])

        # 親がゴミ箱に残っている場合はルートへ付け替える
        # (生きているのにツリーへ表示されない「孤児」を防ぐ)
        if self.parent is not None and self.parent.is_deleted:
            Page.objects.move(self, parent=None, after=None)


class BlockManager(models.Manager):
    def create_block(
        self,
        *,
        page: Page,
        type: str,
        text: str = "",
        checked: bool = False,
        after: "Block | None" = None,
    ) -> "Block":
        position = self._next_position(page=page, after=after)
        return self.create(page=page, type=type, text=text, checked=checked, position=position)

    def _next_position(self, *, page: Page, after: "Block | None") -> str:
        blocks = self.get_queryset().filter(page=page).order_by("position")
        if after is not None:
            following = blocks.filter(position__gt=after.position).first()
            return key_between(after.position, following.position if following else None)
        last = blocks.last()
        return key_between(last.position if last else None, None)

    def move(self, block: "Block", *, after: "Block | None") -> None:
        """ブロックを同一ページ内で after の直後 (None なら先頭) に移動する。"""
        siblings = (
            self.get_queryset().filter(page=block.page).exclude(pk=block.pk).order_by("position")
        )
        if after is None:
            first = siblings.first()
            position = key_between(None, first.position if first else None)
        else:
            following = siblings.filter(position__gt=after.position).first()
            position = key_between(after.position, following.position if following else None)
        block.position = position
        block.save(update_fields=["position", "updated_at"])


class Block(models.Model):
    """ページを構成するコンテンツブロック。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="blocks")
    type = models.CharField(
        max_length=32,
        choices=BlockType.choices,
        default=BlockType.PARAGRAPH,
    )
    text = models.TextField(blank=True, default="")
    checked = models.BooleanField(default=False)
    position = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BlockManager()

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(fields=["page", "position"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()}: {self.text[:30]}"
