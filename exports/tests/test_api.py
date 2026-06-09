"""エクスポート API / タスクの統合テスト。"""
import json

import pytest

from exports.models import Export
from pages.models import Block, BlockType, Page, PageShare, Role
from pages.tests.helpers import post_json

pytestmark = pytest.mark.django_db


def _data(res):
    body = json.loads(res.content)
    assert body["ok"] is True, body
    return body["data"]


@pytest.fixture
def page(user) -> Page:
    p = Page.objects.create_page(owner=user, title="エクスポート対象")
    first = p.blocks.first()
    first.type = BlockType.HEADING_1
    first.text = "見出し"
    first.save()
    Block.objects.create_block(page=p, type=BlockType.PARAGRAPH, text="本文です")
    return p


def test_create_export_runs_and_returns_markdown(authenticated_client, page):
    # 既定は同期実行なので、作成レスポンスの時点で done + content が入っている。
    res = post_json(
        authenticated_client,
        "/api/exports/",
        {"page_id": str(page.id), "format": "markdown"},
    )
    assert res.status_code == 201
    data = _data(res)["export"]
    assert data["status"] == "done"
    assert "# エクスポート対象" in data["content"]  # タイトルが H1
    assert "# 見出し" in data["content"]
    assert "本文です" in data["content"]


def test_get_export_status(authenticated_client, page):
    res = post_json(authenticated_client, "/api/exports/", {"page_id": str(page.id)})
    export_id = _data(res)["export"]["id"]
    res = authenticated_client.get(f"/api/exports/{export_id}/")
    assert _data(res)["export"]["status"] == "done"


def test_create_export_rejects_unsupported_format(authenticated_client, page):
    res = post_json(
        authenticated_client, "/api/exports/", {"page_id": str(page.id), "format": "pdf"}
    )
    assert res.status_code == 400


def test_export_requires_login(client, page):
    res = post_json(client, "/api/exports/", {"page_id": str(page.id)})
    assert res.status_code == 401


def test_export_hidden_from_non_member(client, page, other_user):
    client.force_login(other_user)
    res = post_json(client, "/api/exports/", {"page_id": str(page.id)})
    assert res.status_code == 404  # 存在を漏らさない


def test_viewer_can_export(client, page, other_user):
    PageShare.objects.create(page=page, user=other_user, role=Role.VIEWER)
    client.force_login(other_user)
    res = post_json(client, "/api/exports/", {"page_id": str(page.id)})
    assert res.status_code == 201


def test_get_export_hidden_from_non_member(authenticated_client, client, page, other_user):
    res = post_json(authenticated_client, "/api/exports/", {"page_id": str(page.id)})
    export_id = _data(res)["export"]["id"]
    client.force_login(other_user)
    res = client.get(f"/api/exports/{export_id}/")
    assert res.status_code == 404


def test_get_missing_export_404(authenticated_client):
    res = authenticated_client.get("/api/exports/00000000-0000-0000-0000-000000000000/")
    assert res.status_code == 404


def test_create_export_missing_page_404(authenticated_client):
    res = post_json(
        authenticated_client,
        "/api/exports/",
        {"page_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert res.status_code == 404


def test_export_str(user):
    page = Page.objects.create_page(owner=user)
    export = Export.objects.create(page=page, format="markdown")
    assert "markdown" in str(export)
    assert "pending" in str(export)


# --- タスク -----------------------------------------------------------------


def test_run_export_marks_failed_on_unsupported_format(user):
    page = Page.objects.create_page(owner=user)
    export = Export.objects.create(page=page, format="markdown")
    # API のバリデーションを迂回して不正な形式を仕込む
    Export.objects.filter(pk=export.pk).update(format="xml")
    from exports.tasks import run_export

    run_export(export.id)
    export.refresh_from_db()
    assert export.status == "failed"
    assert export.error


def test_run_export_missing_id_is_noop():
    from exports.tasks import run_export

    run_export("00000000-0000-0000-0000-000000000000")  # 例外を出さない


def test_enqueue_async_path(monkeypatch, settings, user):
    # EXPORTS_ASYNC=True なら RQ 投入経路へ行き、同期実行されない。
    settings.EXPORTS_ASYNC = True
    captured = {}
    monkeypatch.setattr(
        "exports.queue._enqueue_async", lambda export_id: captured.setdefault("id", export_id)
    )
    from exports.queue import enqueue_export

    page = Page.objects.create_page(owner=user)
    export = Export.objects.create(page=page)
    enqueue_export(export)
    assert captured["id"] == export.id
    export.refresh_from_db()
    assert export.status == "pending"  # 同期実行されていない
