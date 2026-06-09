"""Webhook 配信エンジン — HMAC 署名・冪等性・指数バックオフリトライ。

設計(`docs/plan/02-architecture.md` G 節):
- 配信ボディを ``secret`` で **HMAC-SHA256 署名**し、``X-Pynotion-Signature: sha256=...``
  ヘッダで送る(受信側が改竄検知できる)。
- ``event_id`` を ``X-Pynotion-Event`` で送り、``WebhookDelivery`` の一意制約で
  **冪等性**を担保(同じイベントを二重配信しない。done 済みは再送しない)。
- ネットワーク失敗・非 2xx は**指数バックオフ**で ``max_attempts`` 回まで再試行する。

外部 URL への POST は SSRF 面があるため、登録時にスキームを検証し(``validate_url``)、
ループバック/プライベートホストを拒否する。
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlparse

SIGNATURE_HEADER = "X-Pynotion-Signature"
EVENT_HEADER = "X-Pynotion-Event"
EVENT_ID_HEADER = "X-Pynotion-Event-Id"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = 5

_DELIVERY_FIELDS = ["status", "attempts", "last_status_code", "error", "updated_at"]


def generate_secret() -> str:
    return secrets.token_hex(32)


def sign(secret: str, body: bytes) -> str:
    """ボディの HMAC-SHA256 署名(``sha256=<hex>`` 形式)。"""
    mac = hmac.HMAC(secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _is_internal_host(host: str) -> bool:
    """ループバック/プライベート宛先か(リテラル IP + よくある内部ホスト名)。

    DNS 解決はしない(ネットワーク非依存・テスト安定)。DNS リバインディングまでは
    防がない割り切り(基本的な SSRF 対策に留める)。
    """
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith((".local", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 非 IP のホスト名
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved


def validate_url(url: str) -> str:
    """登録 URL を検証する(http/https のみ、内部宛先を拒否 = 基本的な SSRF 対策)。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Webhook URL は http(s) で指定してください")
    host = parsed.hostname
    if not host:
        raise ValueError("Webhook URL のホストが不正です")
    if _is_internal_host(host):
        raise ValueError("内部ネットワーク宛ての Webhook URL は登録できません")
    return url


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """リダイレクトを辿らない。

    登録時に ``validate_url`` で内部宛先を弾いても、登録した公開 URL が
    ``302 Location: http://169.254.169.254/...`` を返せば内部へ到達できてしまう
    (SSRF 迂回)。配信時はリダイレクトを一切辿らずエラーにする。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "リダイレクトは辿りません", headers, fp)


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


def deliver(  # pragma: no cover - 実 HTTP POST(テストではモックする)
    url: str, body: bytes, headers: dict, *, timeout: int = DEFAULT_TIMEOUT
) -> int:
    """URL へ POST し、HTTP ステータスを返す。非 2xx / ネットワーク失敗 / リダイレクトは例外。"""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with _no_redirect_opener.open(request, timeout=timeout) as response:
        return response.status


def _backoff(attempt: int) -> float:
    """指数バックオフ秒(1, 5, 25, ... 上限 30)。"""
    return min(float(5**attempt), 30.0)


def send_with_retry(
    webhook,
    *,
    event: str,
    event_id,
    payload: dict,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    backoff: Callable[[int], float] = _backoff,
):
    """イベントを 1 つの Webhook へ配信する(冪等 + リトライ)。

    ``(webhook, event_id)`` で配信記録を get_or_create し、既に done なら再送しない。
    失敗時は指数バックオフで ``max_attempts`` 回まで再試行する。
    """
    from .models import WebhookDelivery

    # TODO: 非同期(RQ)で複数ワーカーが同時に同一イベントを処理しうるようになったら、
    # select_for_update でこの「取得 → done 判定 → 配信」を直列化する(現状は同期 ping
    # のみで競合しない)。一意制約は二重行生成までは防ぐ。
    delivery, _ = WebhookDelivery.objects.get_or_create(
        webhook=webhook,
        event_id=event_id,
        defaults={"event": event},
    )
    if delivery.status == WebhookDelivery.Status.DONE:
        return delivery  # 冪等: 成功済みは再送しない

    body = json.dumps(
        {"event": event, "event_id": str(event_id), "data": payload},
        ensure_ascii=False,
    ).encode()
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(webhook.secret, body),
        EVENT_HEADER: event,
        EVENT_ID_HEADER: str(event_id),
    }

    last_error = ""
    last_code: int | None = None
    for attempt in range(max_attempts):
        delivery.attempts += 1
        try:
            last_code = deliver(webhook.url, body, headers)
            delivery.status = WebhookDelivery.Status.DONE
            delivery.last_status_code = last_code
            delivery.error = ""
            delivery.save(update_fields=_DELIVERY_FIELDS)
            return delivery
        except urllib.error.HTTPError as exc:
            last_code = exc.code
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError):
            # 生の例外文字列は内部ホスト/ポート/errno を露出しうるため一般化して保存する。
            last_error = "配信先への接続に失敗しました"
        if attempt < max_attempts - 1:
            sleep(backoff(attempt))

    delivery.status = WebhookDelivery.Status.FAILED
    delivery.last_status_code = last_code
    delivery.error = last_error
    delivery.save(update_fields=_DELIVERY_FIELDS)
    return delivery
