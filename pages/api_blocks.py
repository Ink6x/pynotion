"""ブロック関連の JSON API ビュー。"""
import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from .http import fail, json_api, ok, parse_body
from .models import Block, BlockType, Page
from .serializers import serialize_block


def _validate_type(value: object) -> str:
    if not isinstance(value, str) or value not in BlockType.values:
        raise ValueError(f"不正なブロックタイプです: {value!r}")
    return value


def _resolve_after_block(payload: dict, page: Page) -> "Block | None":
    raw = payload.get("after_id")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("after_id は文字列の UUID を指定してください")
    block = Block.objects.filter(pk=raw, page=page).first()
    if block is None:
        raise ValueError("after_id のブロックが見つかりません")
    return block


@require_POST
@json_api
def block_collection(request: HttpRequest, page_id: uuid.UUID) -> JsonResponse:
    page = Page.objects.alive().filter(pk=page_id).first()
    if page is None:
        return fail("ページが見つかりません", status=404)

    payload = parse_body(request)
    text = payload.get("text", "")
    if not isinstance(text, str):
        raise ValueError("text は文字列を指定してください")

    block = Block.objects.create_block(
        page=page,
        type=_validate_type(payload.get("type", BlockType.PARAGRAPH)),
        text=text,
        checked=bool(payload.get("checked", False)),
        after=_resolve_after_block(payload, page),
    )
    return ok({"block": serialize_block(block)}, status=201)


@require_http_methods(["PATCH", "DELETE"])
@json_api
def block_detail(request: HttpRequest, block_id: uuid.UUID) -> JsonResponse:
    block = Block.objects.filter(pk=block_id).first()
    if block is None:
        return fail("ブロックが見つかりません", status=404)

    if request.method == "DELETE":
        block.delete()
        return ok({"deleted": True})

    payload = parse_body(request)
    update_fields = ["updated_at"]
    if "type" in payload:
        block.type = _validate_type(payload["type"])
        update_fields.append("type")
    if "text" in payload:
        if not isinstance(payload["text"], str):
            raise ValueError("text は文字列を指定してください")
        block.text = payload["text"]
        update_fields.append("text")
    if "checked" in payload:
        block.checked = bool(payload["checked"])
        update_fields.append("checked")
    block.save(update_fields=update_fields)
    return ok({"block": serialize_block(block)})


@require_POST
@json_api
def block_move(request: HttpRequest, block_id: uuid.UUID) -> JsonResponse:
    block = Block.objects.filter(pk=block_id).first()
    if block is None:
        return fail("ブロックが見つかりません", status=404)

    payload = parse_body(request)
    after = _resolve_after_block(payload, block.page)
    Block.objects.move(block, after=after)
    return ok({"block": serialize_block(block)})
