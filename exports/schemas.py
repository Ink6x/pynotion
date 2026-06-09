"""django-ninja 入力スキーマ。"""
import uuid

from ninja import Schema


class ExportCreateIn(Schema):
    page_id: uuid.UUID
    format: str = "markdown"
