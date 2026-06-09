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

from .models import Export
from .queue import enqueue_export
from .schemas import ExportCreateIn
from .serializers import serialize_export

router = Router(tags=["exports"])


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
