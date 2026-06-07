"""JSON API 共通ヘルパー — レスポンス封筒とボディ解析。"""
import functools
import json
from collections.abc import Callable

from django.http import HttpRequest, JsonResponse


def ok(data: dict, status: int = 200) -> JsonResponse:
    """成功レスポンス。"""
    return JsonResponse({"ok": True, "data": data, "error": None}, status=status)


def fail(message: str, status: int = 400) -> JsonResponse:
    """失敗レスポンス。"""
    return JsonResponse({"ok": False, "data": None, "error": message}, status=status)


def parse_body(request: HttpRequest) -> dict:
    """リクエストボディを dict として解析する。不正なら ValueError。"""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError as exc:
        raise ValueError("リクエストボディが不正な JSON です") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON オブジェクトを指定してください")
    return data


def json_api(view: Callable) -> Callable:
    """API 共通処理 — 認証チェックとエラー変換。

    - 未認証は 401 (SPA 用 API のためリダイレクトではなく JSON で返す)
    - ValueError (バリデーション) は 400
    - PermissionError (認可不足) は 403
    - LookupError (アクセス権なし = 存在を漏らさない) は 404
    """

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: object, **kwargs: object) -> JsonResponse:
        if not request.user.is_authenticated:
            return fail("ログインが必要です", status=401)
        try:
            return view(request, *args, **kwargs)
        except ValueError as exc:
            return fail(str(exc), status=400)
        except PermissionError as exc:
            return fail(str(exc), status=403)
        except LookupError as exc:
            return fail(str(exc), status=404)

    return wrapper
