"""エクスポートの JSON シリアライザ。"""
from .models import Export


def serialize_export(export: Export) -> dict:
    return {
        "id": str(export.id),
        "page_id": str(export.page_id),
        "format": export.format,
        "status": export.status,
        "content": export.content,
        "error": export.error,
        "created_at": export.created_at.isoformat(),
    }
