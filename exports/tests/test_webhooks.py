"""Webhook 配信エンジンのテスト(署名・URL 検証・リトライ・冪等性)。"""
import urllib.error
import uuid

import pytest

from exports import webhooks
from exports.models import Webhook, WebhookDelivery
from exports.webhooks import sign, validate_url
from pages.models import Page

# --- 署名 / URL 検証(純関数)---------------------------------------------


@pytest.mark.unit
def test_sign_is_deterministic_hmac():
    sig = sign("secret", b"body")
    assert sig.startswith("sha256=")
    assert sign("secret", b"body") == sig  # 決定的
    assert sign("other", b"body") != sig  # 鍵が変われば変わる


@pytest.mark.unit
def test_validate_url_accepts_public_https():
    assert validate_url("https://example.com/hook") == "https://example.com/hook"


@pytest.mark.unit
def test_backoff_is_capped():
    from exports.webhooks import _backoff

    assert webhooks._backoff(0) == 1.0
    assert webhooks._backoff(1) == 5.0
    assert _backoff(10) == 30.0  # 上限でクランプ


@pytest.mark.unit
def test_no_redirect_handler_raises_instead_of_following():
    # リダイレクトを辿らず HTTPError にする(登録後リダイレクトでの SSRF 迂回を防ぐ)
    handler = webhooks._NoRedirectHandler()

    class _Req:
        full_url = "https://example.com/hook"

    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(_Req(), None, 302, "Found", {}, "http://169.254.169.254/")


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",  # スキーム不正
        "http://localhost/x",  # ループバック名
        "http://127.0.0.1/x",  # ループバック IP
        "http://10.0.0.5/x",  # プライベート
        "http://169.254.169.254/latest",  # link-local(メタデータ)
        "http://db.internal/x",  # 内部名
        "https:///nohost",  # ホストなし
    ],
)
def test_validate_url_rejects_unsafe(url):
    with pytest.raises(ValueError):
        validate_url(url)


# --- 配信エンジン(DB)----------------------------------------------------

pytestmark = pytest.mark.django_db


@pytest.fixture
def webhook(user) -> Webhook:
    page = Page.objects.create_page(owner=user)
    return Webhook.objects.create(
        page=page, url="https://example.com/hook", secret="s3cr3t"
    )


def _send(webhook, event_id=None, **kw):
    return webhooks.send_with_retry(
        webhook,
        event="ping",
        event_id=event_id or uuid.uuid4(),
        payload={"x": 1},
        sleep=lambda _s: None,
        **kw,
    )


def test_delivery_success(monkeypatch, webhook):
    monkeypatch.setattr(webhooks, "deliver", lambda *a, **k: 200)
    delivery = _send(webhook)
    assert delivery.status == WebhookDelivery.Status.DONE
    assert delivery.attempts == 1
    assert delivery.last_status_code == 200


def test_retry_then_success(monkeypatch, webhook):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("temporary")
        return 200

    monkeypatch.setattr(webhooks, "deliver", flaky)
    # backoff は既定(_backoff)を使い、sleep だけ no-op にして実時間を待たない
    delivery = webhooks.send_with_retry(
        webhook, event="ping", event_id=uuid.uuid4(), payload={}, sleep=lambda _s: None
    )
    assert delivery.status == WebhookDelivery.Status.DONE
    assert delivery.attempts == 3  # 2 回失敗 → 3 回目で成功


def test_all_attempts_fail(monkeypatch, webhook):
    def boom(*a, **k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(webhooks, "deliver", boom)
    delivery = _send(webhook, max_attempts=3)
    assert delivery.status == WebhookDelivery.Status.FAILED
    assert delivery.attempts == 3
    # 接続失敗は内部情報を漏らさない一般化メッセージで保存される
    assert delivery.error == "配信先への接続に失敗しました"


def test_http_error_records_status_code(monkeypatch, webhook):
    def http_error(*a, **k):
        raise urllib.error.HTTPError("https://example.com/hook", 500, "err", {}, None)

    monkeypatch.setattr(webhooks, "deliver", http_error)
    delivery = _send(webhook, max_attempts=1)
    assert delivery.status == WebhookDelivery.Status.FAILED
    assert delivery.last_status_code == 500
    assert "HTTP 500" in delivery.error


def test_idempotent_no_resend_after_done(monkeypatch, webhook):
    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        return 200

    monkeypatch.setattr(webhooks, "deliver", once)
    event_id = uuid.uuid4()
    first = _send(webhook, event_id=event_id)
    second = _send(webhook, event_id=event_id)  # 同じイベント
    assert first.id == second.id
    assert calls["n"] == 1  # 2 度目は配信しない(冪等)
    assert WebhookDelivery.objects.filter(webhook=webhook).count() == 1
