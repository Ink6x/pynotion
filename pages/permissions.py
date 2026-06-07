"""ページ認可 — @require_role デコレータとロール検査ヘルパー。

方針:
- アクセス権が全く無いページは 404 (存在を漏らさない)
- ロール不足 (viewer が編集など) は PermissionError → 403 (http.json_api が変換)
- 未認証は http.json_api が 401 を返すため、ここでは認証済み前提
"""
import functools
import uuid
from collections.abc import Callable

from django.http import HttpRequest, JsonResponse

from .models import Page, Role, role_satisfies

NOT_FOUND_MESSAGE = "ページが見つかりません"


def check_page_role(page: Page, user, min_role: Role) -> None:
    """user が page に min_role 以上を持たなければ例外を送出する。

    アクセス権ゼロは LookupError (呼び出し側で 404 に変換)、
    ロール不足は PermissionError (json_api が 403 に変換)。
    """
    role = page.effective_role(user)
    if role is None:
        raise LookupError(NOT_FOUND_MESSAGE)
    if not role_satisfies(role, min_role):
        raise PermissionError("この操作を行う権限がありません")


def require_role(min_role: Role, *, queryset: str = "alive") -> Callable:
    """page_id を受けるビューに認可を差し込むデコレータ。

    対象ページを取得しロールを検査した上で、ビューへは page_id の
    代わりに Page インスタンスを渡す (二重フェッチ防止)。

    queryset: "alive" (通常) / "trashed" (restore) / "all" (permanent delete)
    """

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(
            request: HttpRequest, page_id: uuid.UUID, *args: object, **kwargs: object
        ) -> JsonResponse:
            qs = {
                "alive": Page.objects.alive(),
                "trashed": Page.objects.trashed(),
                "all": Page.objects.all(),
            }[queryset]
            page = qs.filter(pk=page_id).first()
            if page is None:
                raise LookupError(NOT_FOUND_MESSAGE)  # json_api が 404 に変換
            check_page_role(page, request.user, min_role)
            return view(request, page, *args, **kwargs)

        return wrapper

    return decorator
