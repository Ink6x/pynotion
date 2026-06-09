"""エクスポート API(django-ninja Router)。

既存の ``pages.api`` の ``NinjaAPI`` へ Router 登録(封筒・例外ハンドラ・認可を共有)。
認可はページの ``effective_role`` へ委譲する(viewer 以上ならエクスポートできる)。
"""
import uuid

from ninja import Router

from pages.api import _enforce_write_ratelimit
from pages.http import ok
from pages.models import Page, Role
from pages.permissions import NOT_FOUND_MESSAGE, check_page_role

from .models import Export, Webhook
from .queue import enqueue_export
from .schemas import ExportCreateIn, WebhookCreateIn
from .serializers import serialize_delivery, serialize_export, serialize_webhook
from .webhooks import generate_secret, send_with_retry, validate_url

router = Router(tags=["exports"])
webhooks_router = Router(tags=["webhooks"])


def _get_page_viewer(page_id: uuid.UUID, user) -> Page:
    page = Page.objects.alive().filter(pk=page_id).first()
    if page is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    check_page_role(page, user, Role.VIEWER)
    return page


@router.post("/")
def create_export(request, payload: ExportCreateIn):
    _enforce_write_ratelimit(request)
    if payload.format not in Export.Format.values:
        raise ValueError(f"未対応のエクスポート形式です: {payload.format!r}")
    page = _get_page_viewer(payload.page_id, request.user)
    export = Export.objects.create(
        page=page, requested_by=request.user, format=payload.format
    )
    # 投入(本番は RQ、開発/テストは同期実行)。同期なら戻り時点で完了している。
    enqueue_export(export)
    export.refresh_from_db()
    return ok({"export": serialize_export(export)}, status=201)


@router.get("/{uuid:export_id}/")
def get_export(request, export_id: uuid.UUID):
    export = (
        Export.objects.select_related("page").filter(pk=export_id).first()
    )
    if export is None:
        raise LookupError("エクスポートが見つかりません")
    try:
        check_page_role(export.page, request.user, Role.VIEWER)
    except LookupError:
        raise LookupError("エクスポートが見つかりません") from None
    return {"export": serialize_export(export)}


# --- Webhook ----------------------------------------------------------------


def _get_page_full(page_id: uuid.UUID, user) -> Page:
    """Webhook 操作はデータを外部へ出すため full_access を要求する。"""
    page = Page.objects.alive().filter(pk=page_id).first()
    if page is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    check_page_role(page, user, Role.FULL_ACCESS)
    return page


def _get_webhook(webhook_id: uuid.UUID, user) -> Webhook:
    webhook = Webhook.objects.select_related("page").filter(pk=webhook_id).first()
    if webhook is None:
        raise LookupError("Webhook が見つかりません")
    try:
        check_page_role(webhook.page, user, Role.FULL_ACCESS)
    except LookupError:
        raise LookupError("Webhook が見つかりません") from None
    return webhook


@webhooks_router.post("/")
def create_webhook(request, payload: WebhookCreateIn):
    _enforce_write_ratelimit(request)
    page = _get_page_full(payload.page_id, request.user)
    url = validate_url(payload.url)  # スキーム検証 + 内部宛先拒否 (SSRF 対策)
    webhook = Webhook.objects.create(
        page=page, created_by=request.user, url=url, secret=generate_secret()
    )
    # secret は登録直後の 1 回だけ返す。
    return ok({"webhook": serialize_webhook(webhook, include_secret=True)}, status=201)


@webhooks_router.get("/")
def list_webhooks(request, page_id: uuid.UUID):
    page = _get_page_full(page_id, request.user)
    return {"webhooks": [serialize_webhook(w) for w in page.webhooks.all()]}


@webhooks_router.delete("/{uuid:webhook_id}/")
def delete_webhook(request, webhook_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    webhook = _get_webhook(webhook_id, request.user)
    webhook.delete()
    return {"deleted": True}


@webhooks_router.post("/{uuid:webhook_id}/ping/")
def ping_webhook(request, webhook_id: uuid.UUID):
    """テスト配信(同期・単発)。HMAC 署名付きの ping を送って結果を返す。"""
    _enforce_write_ratelimit(request)
    webhook = _get_webhook(webhook_id, request.user)
    delivery = send_with_retry(
        webhook,
        event="ping",
        event_id=uuid.uuid4(),
        payload={"page_id": str(webhook.page_id), "message": "ping"},
        max_attempts=1,  # 手動テストはリクエストを待たせないよう単発
        sleep=lambda _seconds: None,
    )
    return {"delivery": serialize_delivery(delivery)}
