"""データベースビューの API(django-ninja Router)。

既存の ``pages.api`` の ``NinjaAPI`` インスタンスへ Router として登録する
(封筒 renderer・例外ハンドラ・セッション認証を共有する)。登録は
``pages/urls.py`` で行う。認可はすべて ``Database.page`` の ``effective_role`` に
委譲する(RBAC を二重実装しない)。
"""
import uuid

from ninja import Router

from pages.api import _enforce_write_ratelimit
from pages.http import ok
from pages.models import Page, Role
from pages.permissions import NOT_FOUND_MESSAGE, check_page_role

from .models import (
    Database,
    DatabaseRow,
    DatabaseView,
    PropertySchema,
    ViewType,
    normalize_row_values,
)
from .query import group_rows, rows_for_view, validate_view_spec
from .schemas import (
    DatabaseCreateIn,
    PropertyCreateIn,
    PropertyUpdateIn,
    RowCreateIn,
    RowUpdateIn,
    ViewCreateIn,
    ViewUpdateIn,
)
from .serializers import (
    serialize_database,
    serialize_property,
    serialize_row,
    serialize_view,
)

router = Router(tags=["databases"])


# --- 認可つき取得ヘルパー ---------------------------------------------------


def _get_database(database_id: uuid.UUID, user, min_role: Role) -> Database:
    database = (
        Database.objects.select_related("page")
        .prefetch_related("properties", "views")
        .filter(pk=database_id, page__is_deleted=False)
        .first()
    )
    if database is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    try:
        check_page_role(database.page, user, min_role)
    except LookupError:
        raise LookupError(NOT_FOUND_MESSAGE) from None
    return database


def _get_property(database: Database, property_id: uuid.UUID) -> PropertySchema:
    prop = database.properties.filter(pk=property_id).first()
    if prop is None:
        raise LookupError("プロパティが見つかりません")
    return prop


def _get_row(row_id: uuid.UUID, user, min_role: Role) -> DatabaseRow:
    row = (
        DatabaseRow.objects.select_related("database__page")
        .filter(pk=row_id, database__page__is_deleted=False)
        .first()
    )
    if row is None:
        raise LookupError("行が見つかりません")
    try:
        check_page_role(row.database.page, user, min_role)
    except LookupError:
        raise LookupError("行が見つかりません") from None
    return row


def _get_view(view_id: uuid.UUID, user, min_role: Role) -> DatabaseView:
    view = (
        DatabaseView.objects.select_related("database__page")
        .filter(pk=view_id, database__page__is_deleted=False)
        .first()
    )
    if view is None:
        raise LookupError("ビューが見つかりません")
    try:
        check_page_role(view.database.page, user, min_role)
    except LookupError:
        raise LookupError("ビューが見つかりません") from None
    return view


# --- データベース -----------------------------------------------------------


@router.post("/")
def create_database(request, payload: DatabaseCreateIn):
    _enforce_write_ratelimit(request)
    page = Page.objects.alive().filter(pk=payload.page_id).first()
    if page is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    check_page_role(page, request.user, Role.EDITOR)
    if hasattr(page, "database"):
        raise ValueError("このページは既にデータベースです")
    database = Database.objects.create(page=page)
    return ok({"database": serialize_database(database)}, status=201)


@router.get("/{uuid:database_id}/")
def get_database(request, database_id: uuid.UUID):
    database = _get_database(database_id, request.user, Role.VIEWER)
    return {"database": serialize_database(database)}


# --- プロパティ(列)--------------------------------------------------------


@router.post("/{uuid:database_id}/properties/")
def create_property(request, database_id: uuid.UUID, payload: PropertyCreateIn):
    _enforce_write_ratelimit(request)
    database = _get_database(database_id, request.user, Role.EDITOR)
    prop = PropertySchema.objects.create_property(
        database=database,
        name=payload.name,
        type=payload.type,
        key=payload.key,
        config=payload.config,
    )
    return ok({"property": serialize_property(prop)}, status=201)


@router.patch("/{uuid:database_id}/properties/{uuid:property_id}/")
def update_property(
    request, database_id: uuid.UUID, property_id: uuid.UUID, payload: PropertyUpdateIn
):
    _enforce_write_ratelimit(request)
    database = _get_database(database_id, request.user, Role.EDITOR)
    prop = _get_property(database, property_id)
    fields = payload.model_fields_set
    update_fields = ["updated_at"]
    if "name" in fields and payload.name is not None:
        prop.name = payload.name
        update_fields.append("name")
    if "config" in fields and payload.config is not None:
        prop.config = payload.config
        update_fields.append("config")
    prop.save(update_fields=update_fields)
    return {"property": serialize_property(prop)}


@router.delete("/{uuid:database_id}/properties/{uuid:property_id}/")
def delete_property(request, database_id: uuid.UUID, property_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    database = _get_database(database_id, request.user, Role.EDITOR)
    prop = _get_property(database, property_id)
    # TODO(4-B-6): 既存行の values に残る当該 key は次回 update_row の正規化で
    # 落ちるまで残存する。型変更マイグレーションと併せて一括クリーンアップする。
    prop.delete()
    return {"deleted": True}


# --- 行 ---------------------------------------------------------------------


@router.post("/{uuid:database_id}/rows/")
def create_row(request, database_id: uuid.UUID, payload: RowCreateIn):
    _enforce_write_ratelimit(request)
    database = _get_database(database_id, request.user, Role.EDITOR)
    after = None
    if payload.after_id is not None:
        after = database.rows.filter(pk=payload.after_id).first()
        if after is None:
            raise ValueError("after_id の行が見つかりません")
    row = DatabaseRow.objects.create_row(
        database=database, values=payload.values, after=after
    )
    return ok({"row": serialize_row(row)}, status=201)


@router.patch("/rows/{uuid:row_id}/")
def update_row(request, row_id: uuid.UUID, payload: RowUpdateIn):
    _enforce_write_ratelimit(request)
    row = _get_row(row_id, request.user, Role.EDITOR)
    # 部分更新: 既存値へマージしてから全体を正規化する(未指定キーは保持)。
    merged = {**row.values, **payload.values}
    row.values = normalize_row_values(row.database, merged)
    row.save(update_fields=["values", "updated_at"])
    return {"row": serialize_row(row)}


@router.delete("/rows/{uuid:row_id}/")
def delete_row(request, row_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    row = _get_row(row_id, request.user, Role.EDITOR)
    row.delete()
    return {"deleted": True}


# --- ビュー -----------------------------------------------------------------


def _validate_view_type(value: str) -> str:
    if value not in ViewType.values:
        raise ValueError(f"不正なビュータイプです: {value!r}")
    return value


@router.post("/{uuid:database_id}/views/")
def create_view(request, database_id: uuid.UUID, payload: ViewCreateIn):
    _enforce_write_ratelimit(request)
    database = _get_database(database_id, request.user, Role.EDITOR)
    view_type = _validate_view_type(payload.type)
    # 宣言的 JSON を保存前に検証する(壊れたビューの保存 = 閲覧者の GET が
    # 毎回失敗する stored-bomb を防ぐ)。
    validate_view_spec(
        database, filters=payload.filters, sorts=payload.sorts, group_by=payload.group_by
    )
    view = DatabaseView.objects.create(
        database=database,
        name=payload.name,
        type=view_type,
        filters=payload.filters,
        sorts=payload.sorts,
        group_by=payload.group_by,
    )
    return ok({"view": serialize_view(view)}, status=201)


@router.patch("/views/{uuid:view_id}/")
def update_view(request, view_id: uuid.UUID, payload: ViewUpdateIn):
    _enforce_write_ratelimit(request)
    view = _get_view(view_id, request.user, Role.EDITOR)
    fields = payload.model_fields_set
    update_fields = ["updated_at"]
    if "name" in fields and payload.name is not None:
        view.name = payload.name
        update_fields.append("name")
    if "type" in fields and payload.type is not None:
        view.type = _validate_view_type(payload.type)
        update_fields.append("type")
    if "filters" in fields and payload.filters is not None:
        view.filters = payload.filters
        update_fields.append("filters")
    if "sorts" in fields and payload.sorts is not None:
        view.sorts = payload.sorts
        update_fields.append("sorts")
    if "group_by" in fields and payload.group_by is not None:
        view.group_by = payload.group_by
        update_fields.append("group_by")
    # 変更後の最終状態を保存前に検証する(stored-bomb 防止)。
    validate_view_spec(
        view.database, filters=view.filters, sorts=view.sorts, group_by=view.group_by
    )
    view.save(update_fields=update_fields)
    return {"view": serialize_view(view)}


@router.delete("/views/{uuid:view_id}/")
def delete_view(request, view_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    view = _get_view(view_id, request.user, Role.EDITOR)
    view.delete()
    return {"deleted": True}


@router.get("/views/{uuid:view_id}/rows/")
def view_rows(request, view_id: uuid.UUID):
    """ビューの filters / sorts を適用した行を返す。

    board(group_by あり)はレーンごとにグループ化して返す。
    宣言的フィルタが不正なら ``query`` 層が ValueError(→400)を投げる。
    """
    view = _get_view(view_id, request.user, Role.VIEWER)
    rows = rows_for_view(view)
    if view.type == ViewType.BOARD and view.group_by:
        groups = [
            {"value": g["value"], "rows": [serialize_row(r) for r in g["rows"]]}
            for g in group_rows(view, rows)
        ]
        return {"view": serialize_view(view), "groups": groups}
    return {"view": serialize_view(view), "rows": [serialize_row(r) for r in rows]}
