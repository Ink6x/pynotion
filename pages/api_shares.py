"""共有管理 API。共有の閲覧・追加・変更・削除は full_access のみ。"""
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .http import json_api, ok, parse_body
from .models import Page, PageShare, Role
from .permissions import require_role


def serialize_share(share: PageShare) -> dict:
    return {
        "user_id": share.user_id,
        "username": share.user.username,
        "role": share.role,
    }


@require_http_methods(["GET", "POST"])
@json_api
@require_role(Role.FULL_ACCESS)
def share_collection(request: HttpRequest, page: Page) -> JsonResponse:
    if request.method == "GET":
        shares = page.shares.select_related("user").order_by("created_at")
        return ok({"shares": [serialize_share(s) for s in shares]})

    payload = parse_body(request)

    username = payload.get("username")
    if not isinstance(username, str) or not username:
        raise ValueError("username を指定してください")
    # ユーザー列挙攻撃を防ぐため、不存在と所有者指定で同じメッセージを返す
    target = get_user_model().objects.filter(username=username).first()
    if target is None or target.pk == page.owner_id:
        raise ValueError("指定したユーザーには共有できません")

    role = payload.get("role")
    if role not in Role.values:
        raise ValueError(f"不正なロールです: {role!r}")

    share, created = PageShare.objects.update_or_create(
        page=page, user=target, defaults={"role": role}
    )
    return ok({"share": serialize_share(share)}, status=201 if created else 200)


@require_http_methods(["DELETE"])
@json_api
@require_role(Role.FULL_ACCESS)
def share_detail(request: HttpRequest, page: Page, user_id: int) -> JsonResponse:
    share = PageShare.objects.filter(page=page, user_id=user_id).first()
    if share is None:
        raise LookupError("共有が見つかりません")
    share.delete()
    return ok({"deleted": True})
