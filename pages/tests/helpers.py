"""テスト用 HTTP ヘルパー。

JSON ボディの POST / PATCH を簡潔に書くための共通関数。
"""
import json
from typing import Any

from django.http import HttpResponse
from django.test import Client


def post_json(client: Client, url: str, payload: dict[str, Any]) -> HttpResponse:
    return client.post(url, json.dumps(payload), content_type="application/json")


def patch_json(client: Client, url: str, payload: dict[str, Any]) -> HttpResponse:
    return client.patch(url, json.dumps(payload), content_type="application/json")
