"""Page / Block — Notion のページとブロックを表すモデル。"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .ordering import key_between


class Role(models.TextChoices):
    """ページ共有のロール。値の強さは ROLE_WEIGHT で比較する。"""

    VIEWER = "viewer", "閲覧者"
    COMMENTER = "commenter", "コメント可"
    EDITOR = "editor", "編集者"
    FULL_ACCESS = "full_access", "フルアクセス"


ROLE_WEIGHT = {
    Role.VIEWER: 1,
    Role.COMMENTER: 2,
    Role.EDITOR: 3,
    Role.FULL_ACCESS: 4,
}


def role_satisfies(role: "Role | None", min_role: "Role") -> bool:
    """role が min_role 以上の強さを持つか。"""
    if role is None:
        return False
    return ROLE_WEIGHT[Role(role)] >= ROLE_WEIGHT[min_role]


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
    TOGGLE = "toggle", "トグル"


# ブロックのネスト最大深さ (ルート直下を 0 とする)。循環・無限ネストを防ぐ。
MAX_BLOCK_DEPTH = 5


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
        owner,
        title: str = "",
        icon: str = "",
        parent: "Page | None" = None,
        after: "Page | None" = None,
    ) -> "Page":
        """ページを作成し、空の段落ブロックを 1 つ持たせる。"""
        position = self._next_position(parent=parent, after=after)
        page = self.create(
            owner=owner, title=title, icon=icon, parent=parent, position=position
        )
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
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_pages",
    )
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

    def ancestor_ids(self) -> list[uuid.UUID]:
        """祖先ページの id 列 (親 → ルートの順)。クエリ数 = 深さ - 1。

        is_deleted は見ない。restore() が「親がゴミ箱なら子をルートへ
        付け替える」ため、生きているページの祖先は常に生きている
        (= ゴミ箱の祖先共有が生きたページへ漏れることはない) 。
        """
        ids: list[uuid.UUID] = []
        seen = {self.pk}
        current = self.parent_id
        while current is not None and current not in seen:
            ids.append(current)
            seen.add(current)
            current = (
                Page.objects.filter(pk=current).values_list("parent_id", flat=True).first()
            )
        return ids

    def effective_role(self, user) -> "Role | None":
        """user がこのページに対して持つ実効ロール。

        - owner は常に full_access
        - 自身と祖先チェーン上の PageShare を 1 クエリで取得し、
          最も強いロールを返す (親で共有されたページは子にも継承される)
        - どちらも無ければ None (アクセス不可)
        """
        if not user.is_authenticated:
            return None
        cached = getattr(self, "_role_cache", None)
        if cached is not None and cached[0] == user.pk:
            return cached[1]
        role = self._compute_effective_role(user)
        self._role_cache = (user.pk, role)
        return role

    def _compute_effective_role(self, user) -> "Role | None":
        if self.owner_id == user.pk:
            return Role.FULL_ACCESS
        page_ids = [self.pk, *self.ancestor_ids()]
        # list() で 1 回だけ評価する (bool 判定と max で二重評価しない)
        roles = list(
            PageShare.objects.filter(page_id__in=page_ids, user=user).values_list(
                "role", flat=True
            )
        )
        if not roles:
            return None
        return max((Role(r) for r in roles), key=lambda r: ROLE_WEIGHT[r])

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


class PageShare(models.Model):
    """ページの共有。親ページの共有は子孫へ継承される (effective_role 参照)。"""

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_shares",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["page", "user"], name="unique_share_per_user"),
            # ORM 直接操作でも不正な role を保存させない (DB レベル防衛)
            models.CheckConstraint(
                condition=models.Q(role__in=[choice[0] for choice in Role.choices]),
                name="valid_share_role",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "page"]),
        ]

    def __str__(self) -> str:
        return f"{self.page} → {self.user} ({self.get_role_display()})"


def accessible_page_ids(user) -> set[uuid.UUID]:
    """user が閲覧可能な「生きている」ページ id の集合。

    所有ページ + 直接共有されたページ + その子孫 (共有の継承)。
    クエリ数 = 2 + 共有サブツリーの深さ。
    """
    owned = set(
        Page.objects.alive().filter(owner=user).values_list("pk", flat=True)
    )
    shared = set(
        Page.objects.alive()
        .filter(shares__user=user)
        .values_list("pk", flat=True)
    )
    ids = owned | shared
    # 共有ページの子孫を幅優先で収集 (所有分は親子とも owned に含まれている)
    frontier = shared - owned
    while frontier:
        children = set(
            Page.objects.alive()
            .filter(parent_id__in=frontier)
            .values_list("pk", flat=True)
        )
        frontier = children - ids
        ids |= children
    return ids


class BlockManager(models.Manager):
    def create_block(
        self,
        *,
        page: Page,
        type: str,
        text: str = "",
        checked: bool = False,
        parent: "Block | None" = None,
        after: "Block | None" = None,
    ) -> "Block":
        if parent is not None:
            _validate_block_parent(page=page, parent=parent)
        _validate_after_sibling(after=after, parent=parent)
        position = self._next_position(page=page, parent=parent, after=after)
        return self.create(
            page=page,
            type=type,
            text=text,
            checked=checked,
            parent=parent,
            position=position,
        )

    def _next_position(
        self, *, page: Page, parent: "Block | None", after: "Block | None"
    ) -> str:
        # 並び順は (page, parent) 単位。兄弟だけを対象に midpoint を取る。
        blocks = self.get_queryset().filter(page=page, parent=parent).order_by("position")
        if after is not None:
            following = blocks.filter(position__gt=after.position).first()
            return key_between(after.position, following.position if following else None)
        last = blocks.last()
        return key_between(last.position if last else None, None)

    def move(
        self, block: "Block", *, parent: "Block | None", after: "Block | None"
    ) -> None:
        """ブロックを parent の子として after の直後 (None なら先頭) に移動する。

        parent=None ならルート (ページ直下) へ。循環・深さ・ページ跨ぎは
        ``_validate_block_parent`` で防ぐ。
        """
        if parent is not None:
            _validate_block_parent(page=block.page, parent=parent, moving=block)
        _validate_after_sibling(after=after, parent=parent)
        siblings = (
            self.get_queryset()
            .filter(page=block.page, parent=parent)
            .exclude(pk=block.pk)
            .order_by("position")
        )
        if after is None:
            first = siblings.first()
            position = key_between(None, first.position if first else None)
        else:
            following = siblings.filter(position__gt=after.position).first()
            position = key_between(after.position, following.position if following else None)
        block.parent = parent
        block.position = position
        block.save(update_fields=["parent", "position", "updated_at"])


def _validate_after_sibling(*, after: "Block | None", parent: "Block | None") -> None:
    """after が移動先 (parent) の兄弟であることを保証する。

    position は (page, parent) スコープで採番するため、別の親に属する after を
    基準にすると整合しない順序キーが生成されてしまう。境界で弾く。
    """
    if after is None:
        return
    parent_pk = parent.pk if parent is not None else None
    if after.parent_id != parent_pk:
        raise ValueError("after は移動先と同じ親のブロックを指定してください")


def _validate_block_parent(
    *, page: Page, parent: "Block", moving: "Block | None" = None
) -> None:
    """ブロックを parent の子にしてよいか検証する (不正なら ValueError)。

    - 親は同じページに属していること (ページ跨ぎ禁止)
    - 自身・自身の子孫を親にしないこと (循環禁止)
    - ネスト深さが MAX_BLOCK_DEPTH を超えないこと
      (親の深さ + 1 + 移動するサブツリーの高さ)
    """
    if parent.page_id != page.pk:
        raise ValueError("別のページのブロックを親にはできません")
    if moving is not None:
        if parent.pk == moving.pk or parent.pk in moving.descendant_ids():
            raise ValueError("ブロックを自身の配下に移動することはできません")
    subtree_height = moving.subtree_height() if moving is not None else 0
    if parent.depth() + 1 + subtree_height > MAX_BLOCK_DEPTH:
        raise ValueError("ネストが深すぎます")


class Block(models.Model):
    """ページを構成するコンテンツブロック。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="blocks")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    type = models.CharField(
        max_length=32,
        choices=BlockType.choices,
        default=BlockType.PARAGRAPH,
    )
    text = models.TextField(blank=True, default="")
    checked = models.BooleanField(default=False)
    collapsed = models.BooleanField(default=False)
    position = models.CharField(max_length=255)
    # 楽観ロック用バージョン。本文更新のたびに +1 し、競合検出に使う
    # (クライアントが見ていた version と不一致なら 409)。
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BlockManager()

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(fields=["page", "parent", "position"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()}: {self.text[:30]}"

    def depth(self) -> int:
        """ルート (ページ直下 = 0) からのネスト深さ。クエリ数 = 深さ。"""
        depth = 0
        seen = {self.pk}
        current = self.parent_id
        while current is not None and current not in seen:
            depth += 1
            seen.add(current)
            current = (
                Block.objects.filter(pk=current).values_list("parent_id", flat=True).first()
            )
        return depth

    def descendant_ids(self) -> set[uuid.UUID]:
        """全ての子孫ブロック id の集合。階層ごとにまとめて取得 (クエリ数 = 深さ)。"""
        ids: set[uuid.UUID] = set()
        frontier = [self.pk]
        while frontier:
            children = list(
                Block.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            children = [c for c in children if c not in ids]
            ids.update(children)
            frontier = children
        return ids

    def subtree_height(self) -> int:
        """自身を根とする部分木の高さ (葉のみなら 0)。"""
        height = 0
        frontier = [self.pk]
        while True:
            children = list(
                Block.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            if not children:
                return height
            height += 1
            frontier = children
