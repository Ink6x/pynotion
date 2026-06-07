"""ページ関連の JSON API ビュー。"""
import uuid

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .http import fail, json_api, ok, parse_body
from .models import Page
from .serializers import serialize_block, serialize_page, serialize_tree


def _get_alive_page(page_id: uuid.UUID) -> "Page | None":
    return Page.objects.alive().filter(pk=page_id).first()


def _resolve_optional_page(payload: dict, key: str) -> "Page | None":
    """payload[key] の UUID から生きているページを引く。不正なら ValueError。"""
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} は文字列の UUID を指定してください")
    page = Page.objects.alive().filter(pk=raw).first()
    if page is None:
        raise ValueError(f"{key} のページが見つかりません")
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
        pages = Page.objects.alive().order_by("position")
        return ok({"pages": serialize_tree(pages)})

    payload = parse_body(request)
    page = Page.objects.create_page(
        title=_string_field(payload, "title"),
        icon=_string_field(payload, "icon"),
        parent=_resolve_optional_page(payload, "parent_id"),
        after=_resolve_optional_page(payload, "after_id"),
    )
    return ok({"page": serialize_page(page)}, status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
@json_api
def page_detail(request: HttpRequest, page_id: uuid.UUID) -> JsonResponse:
    page = _get_alive_page(page_id)
    if page is None:
        return fail("ページが見つかりません", status=404)

    if request.method == "GET":
        blocks = [serialize_block(b) for b in page.blocks.order_by("position")]
        return ok({"page": serialize_page(page), "blocks": blocks})

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
def page_restore(request: HttpRequest, page_id: uuid.UUID) -> JsonResponse:
    page = Page.objects.trashed().filter(pk=page_id).first()
    if page is None:
        return fail("ゴミ箱にページが見つかりません", status=404)
    page.restore()
    return ok({"page": serialize_page(page)})


@require_http_methods(["DELETE"])
@json_api
def page_permanent_delete(request: HttpRequest, page_id: uuid.UUID) -> JsonResponse:
    page = Page.objects.filter(pk=page_id).first()
    if page is None:
        return fail("ページが見つかりません", status=404)
    if not page.is_deleted:
        return fail("ゴミ箱にあるページのみ完全削除できます", status=400)
    page.delete()
    return ok({"deleted": True})


@require_GET
@json_api
def trash_list(request: HttpRequest) -> JsonResponse:
    pages = Page.objects.trashed().order_by("-deleted_at")
    return ok({"pages": [serialize_page(p) for p in pages]})


@require_POST
@json_api
def page_move(request: HttpRequest, page_id: uuid.UUID) -> JsonResponse:
    page = _get_alive_page(page_id)
    if page is None:
        return fail("ページが見つかりません", status=404)

    payload = parse_body(request)
    if "parent_id" in payload:
        parent = _resolve_optional_page(payload, "parent_id")
    else:
        parent = page.parent
        if parent is not None and parent.is_deleted:
            return fail("移動先の親ページがゴミ箱にあります", status=400)

    if parent is not None and (parent == page or parent in page.descendants()):
        return fail("ページを自身の配下に移動することはできません", status=400)

    after = _resolve_optional_page(payload, "after_id")
    if after is not None and after.parent_id != (parent.pk if parent else None):
        return fail("after_id は移動先と同じ階層のページを指定してください", status=400)

    Page.objects.move(page, parent=parent, after=after)
    return ok({"page": serialize_page(page)})


@require_GET
@json_api
def search(request: HttpRequest) -> JsonResponse:
    query = request.GET.get("q", "").strip()
    if not query:
        return ok({"pages": []})
    pages = (
        Page.objects.alive()
        .filter(Q(title__icontains=query) | Q(blocks__text__icontains=query))
        .distinct()
        .order_by("-updated_at")
    )
    return ok({"pages": [serialize_page(p) for p in pages]})
