"""django-ninja による API 体系化。

既存の関数ベース API を置き換えつつ、外形 (URL・``{ok, data, error}`` 封筒・
ステータスコード) を完全に維持する。狙いは **OpenAPI / Swagger UI の自動生成** と
**pydantic による書き込みリクエストの型付け**、および書き込み系のレート制限。

設計:
- 成功レスポンスは ``EnvelopeRenderer`` が ``{ok, data, error}`` で包む。
  各オペレーションは「中身 (data)」だけを返す (201 等は ``(status, data)`` タプル)。
- 例外は ``http.fail`` で封筒化し直す (renderer を介さず直接 JsonResponse)。
  ValueError→400 / PermissionError→403 / LookupError→404 / 認証不備→401 /
  レート超過→429。Phase 1 の ``json_api`` と同じ対応表。
- 認証はセッション (``django_auth``) + CSRF。viewer 以上の細かい認可は
  ``permissions.check_page_role`` を流用する。
"""
import json
import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError
from ninja.renderers import BaseRenderer
from ninja.security import django_auth

from .cache import get_cached_tree, invalidate_trees, set_cached_tree
from .http import fail, ok
from .models import Block, BlockType, Page, PageShare, Role, accessible_page_ids
from .permissions import NOT_FOUND_MESSAGE, check_page_role
from .schemas import (
    BlockCreateIn,
    BlockMoveIn,
    BlockUpdateIn,
    PageCreateIn,
    PageMoveIn,
    PageUpdateIn,
    ShareCreateIn,
)
from .search import search_pages
from .serializers import serialize_block, serialize_page, serialize_share, serialize_tree


class EnvelopeRenderer(BaseRenderer):
    """成功レスポンスを ``{ok, data, error}`` 封筒に包む。"""

    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return json.dumps(
            {"ok": True, "data": data, "error": None},
            cls=DjangoJSONEncoder,
            ensure_ascii=False,
        )


# セッション認証 (django_auth = SessionAuth) は CSRF 検証を内包する。
# ninja 1.x では NinjaAPI(csrf=...) は廃止され、認証クラス側が担う。
api = NinjaAPI(
    title="pynotion API",
    version="1.0.0",
    description="ページ・ブロック・共有・検索の JSON API",
    renderer=EnvelopeRenderer(),
    auth=django_auth,
)


@api.exception_handler(AuthenticationError)
def _on_auth_error(request, exc):
    return fail("ログインが必要です", status=401)


@api.exception_handler(Ratelimited)
def _on_ratelimited(request, exc):
    return fail("リクエストが多すぎます。時間をおいて再試行してください", status=429)


@api.exception_handler(ValidationError)
def _on_validation_error(request, exc):
    return fail("リクエストが不正です", status=400)


@api.exception_handler(HttpError)
def _on_http_error(request, exc):
    # ninja 内部の HttpError (ボディ解析失敗 400 等) も封筒で返す。
    # 既定ハンドラは renderer 経由で ok:true になってしまうため上書きする。
    return fail(str(exc), status=exc.status_code)


@api.exception_handler(ValueError)
def _on_value_error(request, exc):
    return fail(str(exc), status=400)


@api.exception_handler(PermissionError)
def _on_permission_error(request, exc):
    return fail(str(exc), status=403)


@api.exception_handler(LookupError)
def _on_lookup_error(request, exc):
    return fail(str(exc), status=404)


# --- 共通ヘルパー -----------------------------------------------------------


def _enforce_write_ratelimit(request) -> None:
    """書き込み系オペレーションのレート制限 (ユーザー単位)。

    超過時は ``Ratelimited`` を送出 (→ 429)。レートは ``settings.WRITE_RATELIMIT``
    を実行時参照するため、テストでは ``override_settings`` で差し替えられる。
    """
    if is_ratelimited(
        request,
        group="api_write",
        key="user",
        rate=settings.WRITE_RATELIMIT,
        method=is_ratelimited.ALL,
        increment=True,
    ):
        raise Ratelimited()


def _get_page(page_id: uuid.UUID, user, min_role: Role, queryset: str = "alive") -> Page:
    """対象ページを取得しロールを検査する (require_role 相当)。"""
    qs = {
        "alive": Page.objects.alive(),
        "trashed": Page.objects.trashed(),
        "all": Page.objects.all(),
    }[queryset]
    page = qs.filter(pk=page_id).first()
    if page is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    check_page_role(page, user, min_role)
    return page


def _resolve_page_ref(page_id: uuid.UUID | None, user, *, min_role: Role | None = None):
    """任意指定の参照ページ (parent_id / after_id) を引く。

    存在しない・アクセス権なしは一律 ValueError (他人のページの存在を漏らさない)。
    """
    if page_id is None:
        return None
    page = Page.objects.alive().filter(pk=page_id).first()
    if page is None or page.effective_role(user) is None:
        raise ValueError("指定したページが見つかりません")
    if min_role is not None:
        check_page_role(page, user, min_role)
    return page


def _resolve_after_block(after_id: uuid.UUID | None, page: Page):
    if after_id is None:
        return None
    block = Block.objects.filter(pk=after_id, page=page).first()
    if block is None:
        raise ValueError("after_id のブロックが見つかりません")
    return block


def _validate_block_type(value: str) -> str:
    if value not in BlockType.values:
        raise ValueError(f"不正なブロックタイプです: {value!r}")
    return value


def _get_editable_block(block_id: uuid.UUID, user) -> Block:
    block = (
        Block.objects.select_related("page").filter(pk=block_id, page__is_deleted=False).first()
    )
    if block is None:
        raise LookupError("ブロックが見つかりません")
    try:
        check_page_role(block.page, user, Role.EDITOR)
    except LookupError:
        raise LookupError("ブロックが見つかりません") from None
    return block


# --- ページ -----------------------------------------------------------------


@api.get("/pages/")
def list_pages(request):
    cached = get_cached_tree(request.user)
    if cached is not None:
        return {"pages": cached}
    ids = accessible_page_ids(request.user)
    pages = Page.objects.alive().filter(pk__in=ids).order_by("position")
    tree = serialize_tree(pages)
    set_cached_tree(request.user, tree)
    return {"pages": tree}


@api.post("/pages/")
def create_page(request, payload: PageCreateIn):
    _enforce_write_ratelimit(request)
    parent = _resolve_page_ref(payload.parent_id, request.user, min_role=Role.EDITOR)
    after = _resolve_page_ref(payload.after_id, request.user)
    if after is not None and after.parent_id != (parent.pk if parent else None):
        raise ValueError("after_id は同じ階層のページを指定してください")
    owner = parent.owner if parent is not None else request.user
    page = Page.objects.create_page(
        owner=owner, title=payload.title, icon=payload.icon, parent=parent, after=after
    )
    invalidate_trees()
    # 201 はステータス込みの封筒を直接返す (ninja は HttpResponse をそのまま通す)。
    return ok({"page": serialize_page(page)}, status=201)


@api.get("/pages/trash/")
def list_trash(request):
    pages = Page.objects.trashed().filter(owner=request.user).order_by("-deleted_at")
    return {"pages": [serialize_page(p) for p in pages]}


@api.get("/pages/{uuid:page_id}/")
def page_detail(request, page_id: uuid.UUID):
    page = _get_page(page_id, request.user, Role.VIEWER)
    blocks = [serialize_block(b) for b in page.blocks.order_by("position")]
    return {"page": serialize_page(page), "blocks": blocks}


@api.patch("/pages/{uuid:page_id}/")
def update_page(request, page_id: uuid.UUID, payload: PageUpdateIn):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.EDITOR)
    fields = payload.model_fields_set
    if "title" in fields:
        page.title = payload.title or ""
    if "icon" in fields:
        page.icon = payload.icon or ""
    if fields & {"title", "icon"}:
        page.save(update_fields=["title", "icon", "updated_at"])
        invalidate_trees()
    return {"page": serialize_page(page)}


@api.delete("/pages/{uuid:page_id}/")
def delete_page(request, page_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.EDITOR)
    page.soft_delete()
    invalidate_trees()
    return {"page": serialize_page(page)}


@api.post("/pages/{uuid:page_id}/restore/")
def restore_page(request, page_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.EDITOR, queryset="trashed")
    page.restore()
    invalidate_trees()
    return {"page": serialize_page(page)}


@api.delete("/pages/{uuid:page_id}/permanent/")
def permanent_delete_page(request, page_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.FULL_ACCESS, queryset="all")
    if not page.is_deleted:
        raise ValueError("ゴミ箱にあるページのみ完全削除できます")
    page.delete()
    invalidate_trees()
    return {"deleted": True}


@api.post("/pages/{uuid:page_id}/move/")
def move_page(request, page_id: uuid.UUID, payload: PageMoveIn):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.EDITOR)
    if "parent_id" in payload.model_fields_set:
        parent = _resolve_page_ref(payload.parent_id, request.user, min_role=Role.EDITOR)
    else:
        parent = page.parent
        if parent is not None and parent.is_deleted:
            raise ValueError("移動先の親ページがゴミ箱にあります")

    if parent is None and page.parent_id is not None and page.owner_id != request.user.pk:
        raise PermissionError("ルートへ移動できるのはページの所有者のみです")
    if parent is not None and (parent == page or parent in page.descendants()):
        raise ValueError("ページを自身の配下に移動することはできません")

    after = _resolve_page_ref(payload.after_id, request.user)
    if after is not None and after.parent_id != (parent.pk if parent else None):
        raise ValueError("after_id は移動先と同じ階層のページを指定してください")

    Page.objects.move(page, parent=parent, after=after)
    invalidate_trees()
    return {"page": serialize_page(page)}


@api.get("/search/")
def search(request, q: str = ""):
    pages = search_pages(request.user, q)
    return {
        "pages": [
            {**serialize_page(p), "snippet": getattr(p, "search_snippet", None)} for p in pages
        ]
    }


# --- ブロック ---------------------------------------------------------------


@api.post("/pages/{uuid:page_id}/blocks/")
def create_block(request, page_id: uuid.UUID, payload: BlockCreateIn):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.EDITOR)
    block = Block.objects.create_block(
        page=page,
        type=_validate_block_type(payload.type),
        text=payload.text,
        checked=payload.checked,
        after=_resolve_after_block(payload.after_id, page),
    )
    return ok({"block": serialize_block(block)}, status=201)


@api.patch("/blocks/{uuid:block_id}/")
def update_block(request, block_id: uuid.UUID, payload: BlockUpdateIn):
    _enforce_write_ratelimit(request)
    block = _get_editable_block(block_id, request.user)
    fields = payload.model_fields_set
    update_fields = ["updated_at"]
    if "type" in fields:
        block.type = _validate_block_type(payload.type)
        update_fields.append("type")
    if "text" in fields:
        block.text = payload.text or ""
        update_fields.append("text")
    if "checked" in fields:
        block.checked = bool(payload.checked)
        update_fields.append("checked")
    block.save(update_fields=update_fields)
    return {"block": serialize_block(block)}


@api.delete("/blocks/{uuid:block_id}/")
def delete_block(request, block_id: uuid.UUID):
    _enforce_write_ratelimit(request)
    block = _get_editable_block(block_id, request.user)
    block.delete()
    return {"deleted": True}


@api.post("/blocks/{uuid:block_id}/move/")
def move_block(request, block_id: uuid.UUID, payload: BlockMoveIn):
    _enforce_write_ratelimit(request)
    block = _get_editable_block(block_id, request.user)
    after = _resolve_after_block(payload.after_id, block.page)
    Block.objects.move(block, after=after)
    return {"block": serialize_block(block)}


# --- 共有 -------------------------------------------------------------------


@api.get("/pages/{uuid:page_id}/shares/")
def list_shares(request, page_id: uuid.UUID):
    page = _get_page(page_id, request.user, Role.FULL_ACCESS)
    shares = page.shares.select_related("user").order_by("created_at")
    return {"shares": [serialize_share(s) for s in shares]}


@api.post("/pages/{uuid:page_id}/shares/")
def create_share(request, page_id: uuid.UUID, payload: ShareCreateIn):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.FULL_ACCESS)
    from django.contrib.auth import get_user_model

    if not payload.username:
        raise ValueError("username を指定してください")
    # ユーザー列挙攻撃を防ぐため、不存在と所有者指定で同じメッセージを返す
    target = get_user_model().objects.filter(username=payload.username).first()
    if target is None or target.pk == page.owner_id:
        raise ValueError("指定したユーザーには共有できません")
    if payload.role not in Role.values:
        raise ValueError(f"不正なロールです: {payload.role!r}")

    share, created = PageShare.objects.update_or_create(
        page=page, user=target, defaults={"role": payload.role}
    )
    invalidate_trees()  # 共有先ユーザーのツリーが変わる
    return ok({"share": serialize_share(share)}, status=201 if created else 200)


@api.delete("/pages/{uuid:page_id}/shares/{int:user_id}/")
def delete_share(request, page_id: uuid.UUID, user_id: int):
    _enforce_write_ratelimit(request)
    page = _get_page(page_id, request.user, Role.FULL_ACCESS)
    share = PageShare.objects.filter(page=page, user_id=user_id).first()
    if share is None:
        raise LookupError("共有が見つかりません")
    share.delete()
    invalidate_trees()  # 共有先ユーザーのツリーが変わる
    return {"deleted": True}
