"""データベースビュー — スキーマレスなテーブル / ボード。

設計(`docs/plan/02-architecture.md` D 節):

- ``Database`` は Page にぶら下げ、共有・権限は ``Page.effective_role`` に委譲する
  (RBAC を二重実装しない)。タイトル / アイコンも Page のものを使う。
- 列定義は ``PropertySchema``(key / type / config)。値は ``DatabaseRow.values``
  の **JSONB(JSONField)** に型なしで持ち、型ごとの検証は ``properties`` に集約。
  EAV ではなく JSONB を選ぶ理由はスキーマ進化の容易さ(判断記録 #4)。
- 並び順は Page / Block と同じ fractional indexing を再利用(ボードの
  グループ間 DnD で他行を更新せずに移動できる)。

JSONB への GIN インデックスは PostgreSQL 専用のため、モデル Meta では宣言せず
Postgres 限定マイグレーション(RunPython の vendor ガード)で作成する
(pages の pg_trgm と同じ作法。makemigrations の状態をバックエンド間で揃える)。
"""
import uuid

from django.db import models

from pages.models import Page
from pages.ordering import key_between

from .properties import PropertyType, empty_value, validate_value

# Enum を Django の choices へ展開(値は properties.PropertyType と一致)。
PROPERTY_TYPE_CHOICES = [(t.value, t.value) for t in PropertyType]


class Database(models.Model):
    """1 つの Page をテーブル / ボードのデータソースにする。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.OneToOneField(
        Page, on_delete=models.CASCADE, related_name="database"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Database({self.page})"

    def schema_map(self) -> dict[str, "PropertySchema"]:
        """key → PropertySchema の辞書(行の値検証に使う)。"""
        return {prop.key: prop for prop in self.properties.all()}


class PropertySchemaManager(models.Manager):
    def create_property(
        self,
        *,
        database: Database,
        name: str,
        type: str,
        key: str | None = None,
        config: dict | None = None,
    ) -> "PropertySchema":
        # 未知の型はここで弾く(DB へ不正な型名を保存させない)。
        ptype = PropertyType(type).value
        last = self.filter(database=database).order_by("position").last()
        return self.create(
            database=database,
            key=key or uuid.uuid4().hex,
            name=name,
            type=ptype,
            config=config or {},
            position=key_between(last.position if last else None, None),
        )


class PropertySchema(models.Model):
    """データベースの 1 列(プロパティ)定義。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    database = models.ForeignKey(
        Database, on_delete=models.CASCADE, related_name="properties"
    )
    # 値辞書のキー。表示名 (name) と分離し、改名で値を失わないようにする。
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=16, choices=PROPERTY_TYPE_CHOICES)
    config = models.JSONField(default=dict, blank=True)
    position = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PropertySchemaManager()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["database", "key"], name="unique_property_key_per_database"
            ),
        ]
        indexes = [
            models.Index(fields=["database", "position"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.type})"


class DatabaseRowManager(models.Manager):
    def create_row(
        self,
        *,
        database: Database,
        values: dict | None = None,
        after: "DatabaseRow | None" = None,
    ) -> "DatabaseRow":
        last = self.filter(database=database).order_by("position").last()
        if after is not None:
            following = (
                self.filter(database=database, position__gt=after.position)
                .order_by("position")
                .first()
            )
            position = key_between(
                after.position, following.position if following else None
            )
        else:
            position = key_between(last.position if last else None, None)
        normalized = normalize_row_values(database, values or {})
        return self.create(database=database, values=normalized, position=position)


class DatabaseRow(models.Model):
    """データベースの 1 行。値は JSONB に key → 値 で保持する。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    database = models.ForeignKey(
        Database, on_delete=models.CASCADE, related_name="rows"
    )
    # 行詳細の本文を持つサブページ(任意)。Notion の「行を開く」に対応。
    page = models.OneToOneField(
        Page,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="database_row",
    )
    values = models.JSONField(default=dict, blank=True)
    position = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DatabaseRowManager()

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(fields=["database", "position"]),
        ]

    def __str__(self) -> str:
        return f"Row({self.id})"


def normalize_row_values(database: Database, values: dict) -> dict:
    """行の値辞書をスキーマに沿って検証・正規化した**新しい辞書**を返す。

    - 定義済みプロパティの値だけを採用する(未定義キーは捨てる = スキーマ拘束)
    - 各値は型ごとに ``validate_value`` で検証・正規化(不正なら ValueError)
    - 欠けているプロパティは型ごとの空値で補完する
    """
    if not isinstance(values, dict):
        raise ValueError("行の値はオブジェクトで指定してください")
    schema = database.schema_map()
    normalized: dict = {}
    for key, prop in schema.items():
        if key in values:
            normalized[key] = validate_value(prop.type, values[key], prop.config)
        else:
            normalized[key] = empty_value(prop.type)
    return normalized
