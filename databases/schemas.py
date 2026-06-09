"""django-ninja 入力スキーマ(pydantic)。書き込み系リクエストの型付け。

部分更新は ``model_fields_set`` で送信有無を判定する(pages/schemas.py と同規約)。
"""
import uuid

from ninja import Schema


class DatabaseCreateIn(Schema):
    # 既存ページをデータベース化する。
    page_id: uuid.UUID


class PropertyCreateIn(Schema):
    name: str
    type: str
    key: str | None = None
    config: dict = {}


class PropertyUpdateIn(Schema):
    name: str | None = None
    config: dict | None = None


class RowCreateIn(Schema):
    values: dict = {}
    after_id: uuid.UUID | None = None


class RowUpdateIn(Schema):
    values: dict = {}


class ViewCreateIn(Schema):
    name: str = "ビュー"
    type: str = "table"
    filters: dict = {}
    sorts: list = []
    group_by: str = ""


class ViewUpdateIn(Schema):
    name: str | None = None
    type: str | None = None
    filters: dict | None = None
    sorts: list | None = None
    group_by: str | None = None
