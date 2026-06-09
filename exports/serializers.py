"""エクスポート / Webhook の JSON シリアライザ。"""
from .models import Export, Webhook, WebhookDelivery


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


def serialize_webhook(webhook: Webhook, *, include_secret: bool = False) -> dict:
    data = {
        "id": str(webhook.id),
        "page_id": str(webhook.page_id),
        "url": webhook.url,
        "is_active": webhook.is_active,
        "created_at": webhook.created_at.isoformat(),
    }
    # secret は登録直後の 1 回だけ返す(以降は伏せる)。
    if include_secret:
        data["secret"] = webhook.secret
    return data


def serialize_delivery(delivery: WebhookDelivery) -> dict:
    return {
        "id": str(delivery.id),
        "event": delivery.event,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "last_status_code": delivery.last_status_code,
        "error": delivery.error,
    }
