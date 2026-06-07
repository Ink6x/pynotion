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
    """バリデーションエラー (ValueError) を 400 レスポンスに変換する。"""

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: object, **kwargs: object) -> JsonResponse:
        try:
            return view(request, *args, **kwargs)
        except ValueError as exc:
            return fail(str(exc), status=400)

    return wrapper
