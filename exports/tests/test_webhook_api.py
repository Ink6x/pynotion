"""Webhook API の統合テスト(登録・一覧・削除・ping・認可・SSRF)。"""
import json

import pytest

from exports import webhooks
from exports.models import Webhook, WebhookDelivery
from pages.models import Page, PageShare, Role
from pages.tests.helpers import post_json

pytestmark = pytest.mark.django_db


def _data(res):
    body = json.loads(res.content)
    assert body["ok"] is True, body
    return body["data"]


@pytest.fixture
def page(user) -> Page:
    return Page.objects.create_page(owner=user, title="フック対象")


def test_register_webhook_returns_secret_once(authenticated_client, page):
    res = post_json(
        authenticated_client,
        "/api/webhooks/",
        {"page_id": str(page.id), "url": "https://example.com/hook"},
    )
    assert res.status_code == 201
    data = _data(res)["webhook"]
    assert data["url"] == "https://example.com/hook"
    assert data["secret"]  # 登録直後は secret を返す


def test_register_enforces_per_page_limit(authenticated_client, page):
    from exports.api import MAX_WEBHOOKS_PER_PAGE

    for i in range(MAX_WEBHOOKS_PER_PAGE):
        Webhook.objects.create(page=page, url=f"https://example.com/{i}", secret="x")
    res = post_json(
        authenticated_client,
        "/api/webhooks/",
        {"page_id": str(page.id), "url": "https://example.com/over"},
    )
    assert res.status_code == 400  # 上限超過


def test_register_rejects_internal_url(authenticated_client, page):
    res = post_json(
        authenticated_client,
        "/api/webhooks/",
        {"page_id": str(page.id), "url": "http://127.0.0.1/x"},
    )
    assert res.status_code == 400  # SSRF 対策で内部宛先を拒否


def test_list_webhooks_hides_secret(authenticated_client, page):
    Webhook.objects.create(page=page, url="https://example.com/a", secret="x")
    res = authenticated_client.get(f"/api/webhooks/?page_id={page.id}")
    items = _data(res)["webhooks"]
    assert len(items) == 1
    assert "secret" not in items[0]  # 一覧では伏せる


def test_delete_webhook(authenticated_client, page):
    wh = Webhook.objects.create(page=page, url="https://example.com/a", secret="x")
    res = authenticated_client.delete(f"/api/webhooks/{wh.id}/")
    assert res.status_code == 200
    assert not Webhook.objects.filter(pk=wh.id).exists()


def test_ping_delivers_signed_request(monkeypatch, authenticated_client, page):
    captured = {}

    def fake_deliver(url, body, headers, *, timeout=5):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return 200

    monkeypatch.setattr(webhooks, "deliver", fake_deliver)
    wh = Webhook.objects.create(page=page, url="https://example.com/a", secret="sek")
    res = post_json(authenticated_client, f"/api/webhooks/{wh.id}/ping/", {})
    assert res.status_code == 200
    delivery = _data(res)["delivery"]
    assert delivery["status"] == "done"
    # HMAC 署名ヘッダが付いている
    assert captured["headers"]["X-Pynotion-Signature"].startswith("sha256=")
    assert captured["headers"]["X-Pynotion-Event"] == "ping"


def test_ping_reports_failure(monkeypatch, authenticated_client, page):
    import urllib.error

    monkeypatch.setattr(
        webhooks, "deliver", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("x"))
    )
    wh = Webhook.objects.create(page=page, url="https://example.com/a", secret="sek")
    res = post_json(authenticated_client, f"/api/webhooks/{wh.id}/ping/", {})
    assert _data(res)["delivery"]["status"] == "failed"


# --- 認可 -------------------------------------------------------------------


def test_register_requires_full_access(client, page, other_user):
    PageShare.objects.create(page=page, user=other_user, role=Role.EDITOR)
    client.force_login(other_user)
    res = post_json(
        client, "/api/webhooks/", {"page_id": str(page.id), "url": "https://example.com/a"}
    )
    assert res.status_code == 403  # editor では登録できない(full_access のみ)


def test_webhook_hidden_from_non_member(client, page, other_user):
    wh = Webhook.objects.create(page=page, url="https://example.com/a", secret="x")
    client.force_login(other_user)
    res = client.delete(f"/api/webhooks/{wh.id}/")
    assert res.status_code == 404  # 存在を漏らさない


def test_register_requires_login(client, page):
    res = post_json(
        client, "/api/webhooks/", {"page_id": str(page.id), "url": "https://example.com/a"}
    )
    assert res.status_code == 401


def test_register_missing_page_404(authenticated_client):
    res = post_json(
        authenticated_client,
        "/api/webhooks/",
        {"page_id": "00000000-0000-0000-0000-000000000000", "url": "https://example.com/a"},
    )
    assert res.status_code == 404


def test_ping_missing_webhook_404(authenticated_client):
    res = post_json(
        authenticated_client, "/api/webhooks/00000000-0000-0000-0000-000000000000/ping/", {}
    )
    assert res.status_code == 404


def test_delivery_str(page):
    wh = Webhook.objects.create(page=page, url="https://example.com/a", secret="x")
    import uuid

    d = WebhookDelivery.objects.create(webhook=wh, event_id=uuid.uuid4(), event="ping")
    assert "ping" in str(d)
    assert "Webhook(" in str(wh)
