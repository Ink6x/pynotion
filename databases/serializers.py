"""データベース関連モデルの JSON シリアライザ。

pages/serializers.py と同じ方針: モデル → プレーン dict。封筒は renderer が担う。
"""
from .models import Database, DatabaseRow, DatabaseView, PropertySchema


def serialize_property(prop: PropertySchema) -> dict:
    return {
        "id": str(prop.id),
        "key": prop.key,
        "name": prop.name,
        "type": prop.type,
        "config": prop.config,
        "position": prop.position,
    }


def serialize_row(row: DatabaseRow) -> dict:
    return {
        "id": str(row.id),
        "values": row.values,
        "position": row.position,
        "page_id": str(row.page_id) if row.page_id else None,
    }


def serialize_view(view: DatabaseView) -> dict:
    return {
        "id": str(view.id),
        "name": view.name,
        "type": view.type,
        "filters": view.filters,
        "sorts": view.sorts,
        "group_by": view.group_by,
        "position": view.position,
    }


def serialize_database(database: Database) -> dict:
    """データベース本体 + 列定義 + ビュー一覧(行は別取得)。"""
    return {
        "id": str(database.id),
        "page_id": str(database.page_id),
        "properties": [serialize_property(p) for p in database.properties.all()],
        "views": [serialize_view(v) for v in database.views.all()],
    }
