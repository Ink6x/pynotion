"""ページ関連の JSON API ビュー。

認可レベル:
- 閲覧 (detail GET / tree / search) = viewer 以上
- 編集 (create / update / soft delete / restore / move) = editor 以上
- 完全削除 = full_access
- ゴミ箱一覧 = 自分が所有するページのみ (Phase 1 の簡素化)
"""
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .http import json_api, ok, parse_body
from .models import Page, Role, accessible_page_ids
from .permissions import check_page_role, require_role
from .search import search_pages
from .serializers import serialize_block, serialize_page, serialize_tree


def _resolve_optional_page(
    payload: dict, key: str, user, *, min_role: "Role | None" = None
) -> "Page | None":
    """payload[key] の UUID から生きているページを引く。

    不正な値・存在しない・アクセス権が無い場合は一律 ValueError
    (他人のページの存在を漏らさない)。min_role 指定時はロール不足で
    PermissionError。
    """
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} は文字列の UUID を指定してください")
    page = Page.objects.alive().filter(pk=raw).first()
    if page is None or page.effective_role(user) is None:
        raise ValueError(f"{key} のページが見つかりません")
    if min_role is not None:
        check_page_role(page, user, min_role)
    return page


def _string_field(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} は文字列を指定してください")
    return value


@require_http_methods(["GET", "POST"])
@json_api
def page_collection(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        ids = accessible_page_ids(request.user)
        pages = Page.objects.alive().filter(pk__in=ids).order_by("position")
        return ok({"pages": serialize_tree(pages)})

    payload = parse_body(request)
    parent = _resolve_optional_page(payload, "parent_id", request.user, min_role=Role.EDITOR)
    after = _resolve_optional_page(payload, "after_id", request.user)
    if after is not None and after.parent_id != (parent.pk if parent else None):
        raise ValueError("after_id は同じ階層のページを指定してください")

    # 子ページの owner は親の owner を継承する。作成者所有にすると
    # ツリー所有者が自分のツリー内のページへアクセスできなくなるため。
    owner = parent.owner if parent is not None else request.user
    page = Page.objects.create_page(
        owner=owner,
        title=_string_field(payload, "title"),
        icon=_string_field(payload, "icon"),
        parent=parent,
        after=after,
    )
    return ok({"page": serialize_page(page)}, status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
@json_api
@require_role(Role.VIEWER)
def page_detail(request: HttpRequest, page: Page) -> JsonResponse:
    if request.method == "GET":
        blocks = [serialize_block(b) for b in page.blocks.order_by("position")]
        return ok({"page": serialize_page(page), "blocks": blocks})

    check_page_role(page, request.user, Role.EDITOR)

    if request.method == "PATCH":
        payload = parse_body(request)
        if "title" not in payload and "icon" not in payload:
            return ok({"page": serialize_page(page)})
        if "title" in payload:
            page.title = _string_field(payload, "title")
        if "icon" in payload:
            page.icon = _string_field(payload, "icon")
        page.save(update_fields=["title", "icon", "updated_at"])
        return ok({"page": serialize_page(page)})

    page.soft_delete()
    return ok({"page": serialize_page(page)})


@require_POST
@json_api
@require_role(Role.EDITOR, queryset="trashed")
def page_restore(request: HttpRequest, page: Page) -> JsonResponse:
    page.restore()
    return ok({"page": serialize_page(page)})


@require_http_methods(["DELETE"])
@json_api
@require_role(Role.FULL_ACCESS, queryset="all")
def page_permanent_delete(request: HttpRequest, page: Page) -> JsonResponse:
    if not page.is_deleted:
        raise ValueError("ゴミ箱にあるページのみ完全削除できます")
    page.delete()
    return ok({"deleted": True})


@require_GET
@json_api
def trash_list(request: HttpRequest) -> JsonResponse:
    pages = Page.objects.trashed().filter(owner=request.user).order_by("-deleted_at")
    return ok({"pages": [serialize_page(p) for p in pages]})


@require_POST
@json_api
@require_role(Role.EDITOR)
def page_move(request: HttpRequest, page: Page) -> JsonResponse:
    payload = parse_body(request)
    if "parent_id" in payload:
        parent = _resolve_optional_page(
            payload, "parent_id", request.user, min_role=Role.EDITOR
        )
    else:
        parent = page.parent
        if parent is not None and parent.is_deleted:
            raise ValueError("移動先の親ページがゴミ箱にあります")

    if parent is None and page.parent_id is not None and page.owner_id != request.user.pk:
        # ルート階層は所有者の個人スペース。共有ページを他人が
        # ルートへ引き抜くことはできない。
        raise PermissionError("ルートへ移動できるのはページの所有者のみです")

    if parent is not None and (parent == page or parent in page.descendants()):
        raise ValueError("ページを自身の配下に移動することはできません")

    after = _resolve_optional_page(payload, "after_id", request.user)
    if after is not None and after.parent_id != (parent.pk if parent else None):
        raise ValueError("after_id は移動先と同じ階層のページを指定してください")

    Page.objects.move(page, parent=parent, after=after)
    return ok({"page": serialize_page(page)})


@require_GET
@json_api
def search(request: HttpRequest) -> JsonResponse:
    query = request.GET.get("q", "")
    pages = search_pages(request.user, query)
    return ok(
        {
            "pages": [
                {**serialize_page(p), "snippet": getattr(p, "search_snippet", None)}
                for p in pages
            ]
        }
    )
